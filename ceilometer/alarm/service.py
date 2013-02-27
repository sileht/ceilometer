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

import datetime

from oslo.config import cfg

from ceilometer import service
from ceilometer.alarm import storage
from ceilometer.alarm.alarm import Alarm
from ceilometer.alarm.aggregated_metric import AggregatedMetric
from ceilometer.collector import meter as meter_api
from ceilometer.openstack.common import log
from ceilometer.openstack.common import timeutils
from ceilometer.openstack.common.rpc import dispatcher as rpc_dispatcher

LOG = log.getLogger(__name__)

cfg.CONF.register_opts([
    cfg.StrOpt('alarms_topic',
               default='alarms',
               help='the topic ceilometer uses for alarms management',
               ),
])
cfg.CONF.import_opt("metering_topic", "ceilometer.publisher.meter_publish")


class AlarmService(service.PeriodicService):

    def start(self):
        super(AlarmService, self).start()

        storage.register_opts(cfg.CONF)
        self.storage_engine = storage.get_engine(cfg.CONF)
        self.storage_conn = self.storage_engine.get_connection(cfg.CONF)

        self._load_alarm_cache()

    def periodic_tasks(self, context):
        pass

    def _load_alarm_cache(self):
        self._cache_alarms = dict((x, self.storage_conn.alarm_get(x)) for x in
                                  self.storage_conn.alarm_list(enabled=True))
        LOG.debug("alarms loaded: %d", len(self._cache_alarms))

    def initialize_service_hook(self, service):
        self.conn.create_worker(
            cfg.CONF.metering_topic,
            rpc_dispatcher.RpcDispatcher([self]),
            'ceilometer.alarms.' + cfg.CONF.metering_topic,
        )

        self.conn.create_worker(
            cfg.CONF.alarms_topic,
            rpc_dispatcher.RpcDispatcher([self]),
            'ceilometer.alarms.' + cfg.CONF.alarms_topic,
        )

    def add_or_update_alarm(self, context, data):
        self._cache_alarms[data['id']] = Alarm(**data)
        LOG.debug("alarms loaded: %d", len(self._cache_alarms))

    def delete_alarm(self, context, id):
        if id in self._cache_alarms:
            del self._cache_alarms[id]
        LOG.debug("alarms loaded: %d", len(self._cache_alarms))

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

        now = timeutils.utcnow()

        for alarm in self._cache_alarms.values():
            if not alarm.match(meter):
                continue
            LOG.debug("meter %s match alarm: %s", meter, alarm)

            #alarm.load_aggregated_metrics(self.storage_conn)
            #alarm.put_in_aggregated_metrics(meter)

            aggregates = self._cache_aggregated_metric_list(
                alarm_id=alarm.id
            )

            incomplete_timestamp = now - datetime.timedelta(
                seconds=(alarm.aggregate_period * 1.5)
            )

            LOG.debug("%s %s >= %s", aggregates,
                      aggregates and aggregates[0].timestamp or None,
                      incomplete_timestamp)
            if aggregates and aggregates[0].timestamp >= incomplete_timestamp:
                # A aggregated_metric is incomplete, just fill it
                incomplete_aggregate = aggregates.pop(0)
                LOG.debug('Update aggregated_metric %s of alarm: %s',
                          incomplete_aggregate.id, alarm.id)

                incomplete_aggregate.update(meter)
                self._cache_aggregated_metric_update(alarm.id,
                                                     incomplete_aggregate)
            else:
                LOG.debug('Create new aggregated_metric for alarm: %s' %
                          alarm.id)
                # A new aggregated_metric is needed store the received metric
                # So create it and evaluate the alarm for the previous
                incomplete_aggregate = AggregatedMetric(alarm.id)
                incomplete_aggregate.update(meter)
                self._cache_aggregated_metric_add(alarm.id,
                                                  incomplete_aggregate)

            aggregates_to_keep = aggregates[:alarm.evaluation_period]
            aggregates_to_delete = aggregates[alarm.evaluation_period:]

            self._cache_aggregated_metric_delete(alarm, aggregates_to_delete)

            if alarm.check_state(aggregates_to_keep):
                self.storage_conn.alarm_update(alarm)

    def _cache_aggregated_metric_list(self, alarm_id):
        if alarm_id not in self._cache_aggregated_metric:
            self._cache_aggregated_metric[alarm_id] = dict(
                (x, self.storage_conn.aggregated_metric_get(x))
                for x in self.storage_conn.aggregated_metric_list(alarm_id))
        return self._cache_aggregated_metric[alarm_id]

    def _cache_aggregated_metric_delete(self, alarm_id, aggregates):
        for agg in aggregates:
            self.storage_conn.aggregated_metric_delete(agg.id)
            del self._cache_aggregated_metric[alarm_id][agg.id]

    def _cache_aggregated_metric_update(self, alarm_id, aggregated_metric):
        self.storage_conn.aggregated_metric_update(aggregated_metric)
        self._cache_aggregated_metric[alarm_id][aggregated_metric.id] = \
            aggregated_metric

    def _cache_aggregated_metric_add(self, alarm_id, aggregated_metric):
        self.storage_conn.aggregated_metric_add(aggregated_metric)
        self._cache_aggregated_metric[alarm_id][aggregated_metric.id] = \
            aggregated_metric
