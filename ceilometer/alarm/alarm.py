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

import eventlet
import operator
import requests

from ceilometer import exception

from ceilometer.storage import models
from ceilometer.openstack.common import jsonutils
from ceilometer.openstack.common import log
from ceilometer.openstack.common import timeutils

LOG = log.getLogger(__name__)

ALARM_INSUFFICIENT_DATA = 0x00
ALARM_OK = 0x01
ALARM_ALARM = 0x02

STATE_MAP = {
    ALARM_INSUFFICIENT_DATA: 'insufficient data',
    ALARM_OK: 'ok',
    ALARM_ALARM: 'alarm',
}


class Alarm(models.Model):

    def __init__(self, name, counter_name,
                 comparison_operator, threshold, statistic,
                 user_id, project_id,
                 evaluation_period=60,
                 aggregate_period=3,
                 id=None,
                 enabled=True,
                 description="",
                 timestamp=None,
                 state=ALARM_INSUFFICIENT_DATA,
                 state_timestamp=None,
                 ok_actions=[],
                 alarm_actions=[],
                 insufficient_data_actions=[],
                 matching_metadata={}
                 ):

        timestamp = timestamp or timeutils.utcnow()
        state_timestamp = state_timestamp or timeutils.utcnow()

        super(Alarm, self).__init__(
            id=id,
            enabled=enabled,
            name=name,
            description=description,
            timestamp=timestamp,
            counter_name=counter_name,
            user_id=user_id,
            project_id=project_id,
            comparison_operator=comparison_operator,
            threshold=threshold,
            statistic=statistic,
            evaluation_period=evaluation_period,
            aggregate_period=aggregate_period,
            state=state,
            state_timestamp=state_timestamp,
            ok_actions=ok_actions,
            alarm_actions=alarm_actions,
            insufficient_data_actions=
            insufficient_data_actions,
            matching_metadata=matching_metadata)

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

    def __repr__(self):
        return "%s" % self.as_dict()

    @property
    def _actions(self):
        return {
            ALARM_OK: self.ok_actions,
            ALARM_ALARM: self.alarm_actions,
            ALARM_INSUFFICIENT_DATA: self.insufficient_data_actions
        }

    @property
    def state_reason(self):
        return  _('Threshold %s reached') % self.threshold

    @property
    def state_text(self):
        return STATE_MAP.get(self.state, "unknown")

    @property
    def state_reason_data(self):
        return jsonutils.dumps({
            'threshold': self.threshold,
        })

    def match(self, meter):
        """Check if the alarm apply to this meter

        Note: when a metadata value is a list, we check that the meter value
        match one of its elements.

        Example: This allow to made a alarm that calculate the statistics
        of the cpu usage for multiple instances
        """
        if self.counter_name != meter['counter_name']:
            return False

        for k, v in self.matching_metadata.iteritems():
            if k not in meter:
                return False
            if not isinstace(v, list):
                v = [v]
                if meter[k] not in v:
                    return False

        return True

    def load_aggregated_metrics(self, conn):
        if not self._cached_aggregated_metric:
            self.storage_conn = conn
            self._cached_aggregated_metric[alarm_id] = dict(
                (x, conn.aggregated_metric_get(x))
                for x in conn.aggregated_metric_list(alarm_id))

    def put_in_aggregated_metrics(self, meter):
        pass

    def check_state(self, aggregates):
        """this function assume that 'aggregates' contains only the
        aggregate that match the alarm/evaluation_period/aggregate_period

        return True if state change
        """

        LOG.debug('alarm %s: checking state for meter %s', self.name,
                  self.counter_name)

        LOG.debug('alarm %s: %d aggregates to compare (needs %d)', self.name,
                  len(aggregates), self.evaluation_period)

        op = getattr(operator, self.comparison_operator)

        if len(aggregates) < self.evaluation_period:
            current_state = ALARM_INSUFFICIENT_DATA
        else:
            current_state = ALARM_ALARM
            for aggregate in aggregates:
                LOG.debug('alarm %s: not %s %s %s ?', self.name,
                          getattr(aggregate, self.statistic),
                          self.comparison_operator, float(self.threshold))
                if not op(getattr(aggregate, self.statistic),
                          float(self.threshold)):
                    current_state = ALARM_OK
                    break

        if current_state != self.state:
            LOG.debug('alarm %s: state change from %s to %s',
                      self.name, STATE_MAP.get(self.state, "unknown"),
                      STATE_MAP.get(current_state, "unknown"))

            self.state = current_state
            self.state_timestamp = timeutils.utcnow()
            self._do_actions()
            return True
        return False

    _KEYS_TO_PUBLISH = ['id', 'enabled', 'name', 'description',
                        'counter_name', 'comparison_operator',
                        'threshold', 'statistic', 'evaluation_period',
                        'aggregate_period', 'user_id', 'project_id',
                        'timestamp', 'state_text', 'state', 'state_timestamp',
                        'matching_metadata', 'ok_actions', 'alarm_actions',
                        'insufficient_data_actions']

    def _do_actions(self):
        for action in self._actions[self.state]:
            data = dict((k, getattr(self, k)) for k in self._KEYS_TO_PUBLISH)
            #TODO(sileht): security issue, no check have been done on the url
            #anyone can call a internal url
            LOG.debug("call actions: %s", action % ActionUrlArgs(data))
            eventlet.spawn_n(requests.post, action % ActionUrlArgs(data),
                             data=data)


class ActionUrlArgs(dict):
    def __getitem__(self, k):
        return super(ActionUrlArgs, self).get(k, "invalid alarm field")
