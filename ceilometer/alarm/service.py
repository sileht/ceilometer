# -*- encoding: utf-8 -*-
#
# Copyright © 2013 eNovance <licensing@enovance.com>
#
# Author: Mehdi Abaakouk <mehdi.abaakouk@enovance.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os

from oslo.config import cfg

from ceilometer import exception
from ceilometer import service
from ceilometer import storage
from ceilometer import utils
from ceilometer.alarm.alarm import Alarm
from ceilometer.collector import meter as meter_api
from ceilometer.openstack.common import jsonutils
from ceilometer.openstack.common import log
from ceilometer.openstack.common import timeutils
from ceilometer.openstack.common.rpc import dispatcher as rpc_dispatcher
import ceilometer.publisher.meter_publish  # for cfg.CONF.metering_topic

OPTS = [
    cfg.StrOpt('alarms_file',
               default='alarms.json',
               help='JSON file representing alarms'),
]

cfg.CONF.register_opts(OPTS)

LOG = log.getLogger(__name__)


class AlarmService(service.PeriodicService):

    def start(self):
        super(AlarmService, self).start()
        self._load_alarms()

        storage.register_opts(cfg.CONF)
        self.storage_engine = storage.get_engine(cfg.CONF)
        self.storage_conn = self.storage_engine.get_connection(cfg.CONF)

    def _load_alarms(self):
        self._alarms = []
        self._alarms_cache = {}
        self._alarms_path = cfg.CONF.alarms_file

        if not os.path.exists(self._alarms_path):
            self._alarms_path = cfg.CONF.find_file(self._alarms_path)
        if not self._alarms_path:
            raise cfg.ConfigFilesNotFoundError([cfg.CONF.alarms_file])

        utils.read_cached_file(self._alarms_path, self._alarms_cache,
                               reload_func=self._set_alarms)

    def _set_alarms(self, data):
        self._alarms = []
        for data in jsonutils.loads(data):
            try:
                alarm = Alarm(**data)
            except exception.InvalidComparisonOperator:
                LOG.exception(_("Fail to load a alarm"))
            else:
                self._alarms.append(alarm)

    def periodic_tasks(self, context):
        pass

    def initialize_service_hook(self, service):
        self.conn.create_worker(
            cfg.CONF.metering_topic,
            rpc_dispatcher.RpcDispatcher([self]),
            'ceilometer.alarms.' + cfg.CONF.metering_topic,
        )

    def record_metering_data(self, context, data):
        """This method is triggered when metering data is
        cast from an agent.
        """
        # We may have receive only one counter on the wire
        if not isinstance(data, list):
            data = [data]

        for meter in data:
            #LOG.info('metering data %s for %s @ %s: %s',
            #         meter['counter_name'],
            #         meter['resource_id'],
            #         meter.get('timestamp', 'NO TIMESTAMP'),
            #         meter['counter_volume'])
            if meter_api.verify_signature(meter, cfg.CONF.metering_secret):
                if meter.get('timestamp'):
                    ts = timeutils.parse_isotime(meter['timestamp'])
                    meter['timestamp'] = timeutils.normalize_time(ts)
                self._check_alarms(meter)
            else:
                LOG.warning(
                    'message signature invalid, discarding message: %r',
                    meter)

    def _check_alarms(self, meter):
        for alarm in self._get_alarms_for_meter(meter):
            alarm.check_state(self.storage_conn, meter)

    def _get_alarms_for_meter(self, meter):
        return [alarm for alarm in self._alarms
                if alarm.match_meter(meter)]
