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

from oslo.config import cfg

from ceilometer import service
from ceilometer.alarm import storage
from ceilometer.alarm.alarm import Alarm
from ceilometer.collector import meter as meter_api
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

        storage.register_opts(cfg.CONF)
        self.storage_engine = storage.get_engine(cfg.CONF)
        self.storage_conn = self.storage_engine.get_connection(cfg.CONF)

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
        #TODO: each alarm.check_state should be in a thread

        #TODO: filter with counter metadata
        # metaquery = []
        # for k in ['counter_type', 'user_id', 'project_id', 'resource_id']:
        #     if k in meter:
        #         metaquery.append((k, meter[k]))
        #
        # if 'resource_metadata' in metaquery:
        #     for k, v in meter['resource_metadata'].iteritems():
        #         metaquery.append((k, v))

        for values in self.storage_conn.alarm_list(
                counter_name=meter['counter_name']):

            alarm = Alarm(**values)
            aggregates = list(self.storage_conn.aggregated_metric_list(
                alarm.id,
                limit=alarm.evaluation_period,
                start=alarm.oldest_timestamp
            ))

            if not aggregates:
                aggregates = []

            alarm.update_aggregated_metric_data(meter, aggregates)

            self.storage_conn.aggregated_metric_update(
                aggregates[0].get('id', None),
                aggregates[0]
            )

            if alarm.check_state(aggregates):
                self.storage_conn.alarm_update_state(alarm.id,
                                                     alarm.state,
                                                     alarm.state_timestamp)
