# -*- encoding: utf-8 -*-
#
# Copyright © 2013 eNovance <licensing@enovance.com>
#
# Author: Mehdi Abaakouk <mehdi.abaakouk@enovance.com>
#
# Licensed under the Apache License, Version 2.0 (the 'License'); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import datetime
import operator
import subprocess

from ceilometer import exception

from ceilometer.openstack.common import jsonutils
from ceilometer.openstack.common import log
from ceilometer.openstack.common import timeutils

LOG = log.getLogger(__name__)

ALARM_INSUFFICIENT_DATA = 0x00
ALARM_OK = 0x01
ALARM_ALARM = 0x02


class Alarm(object):

    _STATE_MAP = {
        ALARM_INSUFFICIENT_DATA: 'insufficient data',
        ALARM_OK: 'ok',
        ALARM_ALARM: 'alarm',
    }

    def __init__(self, **kwargs):

        self.id = kwargs.pop('id', None)
        self.enabled = kwargs.pop('enabled', True)
        self.name = kwargs.pop('name')
        self.description = kwargs.pop('description', None)
        self.timestamp = kwargs.pop('timestamp', timeutils.utcnow())
        self.counter_name = kwargs.pop('counter_name')

        #TODO: Should be mandatory
        self.user_id = kwargs.pop('user_id', None)
        self.project_id = kwargs.pop('project_id', None)

        self.comparison_operator = kwargs.pop('comparison_operator')
        self.threshold = kwargs.pop('threshold')
        self.statistic = kwargs.pop('statistic')

        self.evaluation_period = kwargs.pop('evaluation_period')
        self.aggregate_period = kwargs.pop('aggregate_period')

        self.state = kwargs.pop('state', None)
        self.state_timestamp = kwargs.pop('state_timestamp',
                                          timeutils.utcnow())

        self.ok_actions = kwargs.pop('ok_actions', [])
        self.alarm_actions = kwargs.pop('alarm_actions', [])
        self.insufficient_data_actions = kwargs.pop(
            'insufficient_data_actions', [])

        self.alarm_metadatas = kwargs.pop('alarm_metadatas', [])

        if kwargs:
            raise exception.AlarmParameterUnknown(name=self.name,
                                                  params=kwargs)

        try:
            getattr(operator, self.comparison_operator)
        except AttributeError:
            raise exception.InvalidComparisonOperator(
                name=self.name,
                comparison_operator=self.comparison_operator)

        """
        Other fields we should have (or calculate the value) for CloudWatch API

        self.history = []
        self.arn = ""

        self.unit = None

        self.namespace = None  # howto match this to a metric data,
        the source of the metric ? (ie : 'EC2: Instance Metric')

        # Unit handle by CloudWatch
        # Seconds, Microseconds, Milliseconds Bytes, Kilobytes, Megabytes,
        # Gigabytes, Terabytes, Bits, Kilobits, Megabits, Gigabits, Terabits,
        # Percent, Count, Bytes/Second, Kilobytes/Second, Megabytes/Second,
        # Gigabytes/Second, Terabytes/Second, Bits/Second, Kilobits/Second,
        # Megabits/Second, Gigabits/Second), Terabits/Second, Count/Second,
        # None

        """

    def __getitem__(self, k):
        return getattr(self, k)

    def iteritems(self):
        for k in ['id', 'enabled', 'name', 'description', 'counter_name',
                  'comparison_operator', 'threshold', 'statistic',
                  'evaluation_period', 'aggregate_period',
                  'user_id', 'project_id', 'timestamp',
                  'state', 'state_timestamp', 'alarm_metadatas',
                  'ok_actions', 'alarm_actions', 'insufficient_data_actions']:
            yield k, getattr(self, k)

    def items(self):
        return dict(self.iteritems())

    @property
    def oldest_timestamp(self):
        """oldest timestamp that could be used for the alarm
        """
        timestamp = timeutils.utcnow()
        timestamp -= datetime.timedelta(seconds=(self.evaluation_period *
                                        self.aggregate_period))
        timestamp -= datetime.timedelta(seconds=1)
        return timestamp

    @property
    def state_reason(self):
        return  _('Threshold %s reached') % self.threshold

    @property
    def state_reason_data(self):
        return jsonutils.dumps({
            'threshold': self.threshold,
        })

    def update_aggregated_metric_data(self, meter, aggregates):
        if len(aggregates) == 0:
            need_new_aggregate = True
        else:
            need_new_aggregate = aggregates[0].get('timestamp') <= \
                timeutils.utcnow() - \
                datetime.timedelta(seconds=self.aggregate_period)

        if need_new_aggregate:
            aggregates.insert(0, {
                'alarm_id': self.id,
                'timestamp': timeutils.utcnow(),
            })

        aggregate = aggregates[0]

        m = meter['counter_volume']
        aggregate['sum'] = aggregate.get('sum', 0.0) + m
        aggregate['maximum'] = max(aggregate.get('maximum', m), m)
        aggregate['minimum'] = min(aggregate.get('minimum', m), m)
        aggregate['sample_count'] = aggregate.get('sample_count', 0.0) + 1.0
        aggregate['average'] = aggregate['sum'] / aggregate['sample_count']

        return aggregates

    def check_state(self, aggregates):
        """this function assume that 'aggregates' contains only the
        aggregate that match the alarm/evaluation_period/aggregate_period

        return True if state change
        """

        LOG.debug('alarm %s: checking state for meter %s', self.name,
                  self.counter_name)

        op = getattr(operator, self.comparison_operator)

        if len(aggregates) < self.evaluation_period:
            current_state = ALARM_INSUFFICIENT_DATA
        else:
            current_state = ALARM_OK
            for aggregate in aggregates:
                if op(aggregate[self.statistic], float(self.threshold)):
                    current_state = ALARM_ALARM
                    break

        if current_state != self.state:
            LOG.debug('alarm %s: state change from %s to %s',
                      self.name, self._STATE_MAP[self.state],
                      self._STATE_MAP[current_state])

            self.state = current_state
            self.state_timestamp = timeutils.utcnow()
            self._record_state_changed_to_history()
            self._do_actions()
            return True
        return False

    def _record_state_changed_to_history(self):
        """History not yet implemented
        """
        pass

    def _do_actions(self):
        if self.state == ALARM_OK:
            for action in self.ok_actions:
                self._execute(action)
        if self.state == ALARM_ALARM:
            for action in self.alarm_actions:
                self._execute(action)
        if self.state == ALARM_INSUFFICIENT_DATA:
            for action in self.insufficient_data_actions:
                self._execute(action)

    def _execute(self, action):
        env = {}
        for k, v in self.iteritems():
            env["CEILOMETER_ALARM_%s" % k.upper()] = str(v)
        try:
            p = subprocess.Popen(action, shell=True, env=env)
            p.communicate()
            if p.returncode != 0:
                LOG.warning('alarm %s: action %s return %s',
                            self.name, action, p.returncode)
            else:
                LOG.debug('alarm %s: successful start action %s ',
                          self.name, action)
                return True
        except OSError as e:
            LOG.error('alarm %s: action %s execution failed %s',
                      self.name, action, e)
        return False
