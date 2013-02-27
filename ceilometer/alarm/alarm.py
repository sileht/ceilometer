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

import operator
import subprocess

from ceilometer import exception
from ceilometer import storage
from ceilometer.openstack.common import jsonutils
from ceilometer.openstack.common import log

LOG = log.getLogger(__name__)

ALARM_INSUFFICIENT_DATA = 0x00
ALARM_OK = 0x01
ALARM_ALARM = 0x02

_STATE_MAP = {
    ALARM_INSUFFICIENT_DATA: 'insufficient data',
    ALARM_OK: 'ok',
    ALARM_ALARM: 'alarm',
}


class Alarm(object):
    def __init__(self, name, counter_name, comparison_operator,
                 threshold, statistic, period, **kwargs):
        self.name = name
        self.counter_name = counter_name
        self.comparison_operator = comparison_operator
        self.threshold = threshold
        self.statistic = statistic
        self.period = period

        self.description = kwargs.pop('description', None)

        self.resource_id = kwargs.pop('resource_id', None)

        self.ok_action = kwargs.pop('ok_action', None)
        self.alarm_action = kwargs.pop('alarm_action', None)
        self.insufficient_data_action = kwargs.pop('insufficient_data_action',
                                                   None)

        self.state = ALARM_INSUFFICIENT_DATA

        try:
            getattr(operator, self.comparison_operator)
        except AttributeError:
            raise exception.InvalidComparisonOperator(
                name=self.name,
                comparison_operator=self.comparison_operator)

        """
        Other fields we should have (or calculate the value) for CloudWatch API

        self.<*>_action should be a list of action

        self.history = []
        self.last_modified = None  # datetime ?
        self.actions_enabled = True
        self.arn = ""

        self.unit = None

        self.dimensions = None  # howto match this to a metric data, tenant,
                                  user, instance, container ?

        self.namespace = None  # howto match this to a metric data,
        the source of the metric ? (ie : 'EC2: Instance Metric')

        self.state_last_modified = None  # datetime

        # Unit handle by CloudWatch
        # Seconds, Microseconds, Milliseconds Bytes, Kilobytes, Megabytes,
        # Gigabytes, Terabytes, Bits, Kilobits, Megabits, Gigabits, Terabits,
        # Percent, Count, Bytes/Second, Kilobytes/Second, Megabytes/Second,
        # Gigabytes/Second, Terabytes/Second, Bits/Second, Kilobits/Second,
        # Megabits/Second, Gigabits/Second), Terabits/Second, Count/Second,
        # None

        """

    def _state_reason(self):
        return  _("Threshold %s reached") % self.threshold
    state_reason = property(_state_reason)

    def _state_reason_data(self):
        return jsonutils.dumps({
            "threshold": self.threshold,
        })
    state_reason_data = property(_state_reason_data)

    def match_meter(self, meter):
        """Check if the alarm apply to this meter
        Actually only the meter is checked but more checks should be done
        (like ressource_id, project_id, metadata, ....)"""

        return self.counter_name == meter['counter_name'] and \
            (not self.resource_id or
                self.resource_id == meter['resource_id'])

    def check_state(self, conn, meter):
        LOG.debug('alarm %s: checking state for meter %s', self.name,
                  meter)
        f = storage.EventFilter(
            meter=meter['counter_name'],
            resource=self.resource_id,
        )
        result = conn.get_meter_statistics(f, period=self.period)[0]
        LOG.debug("alarm %s: statistic result: %s", self.name, result)

        op = getattr(operator, self.comparison_operator)

        #FIXME: this is a arbitrary period threshold
        #but how to know when we have enough data to handle or not the actio
        period_threshold = 10

        if int(result['duration'] * 60.0) - result['period'] \
                + period_threshold < 0:
            current_state = ALARM_INSUFFICIENT_DATA
        elif op(result[self.statistic], float(self.threshold)):
            current_state = ALARM_ALARM
        else:
            current_state = ALARM_OK

        if current_state != self.state:
            LOG.debug('alarm %s: state change from %s to %s',
                      self.name, _STATE_MAP[self.state],
                      _STATE_MAP[current_state])
            self.state = current_state
            self._do_action(result)

    def _do_action(self, result):
        if self.state == ALARM_ALARM:
            self._execute(self.alarm_action, result)
        if self.state == ALARM_OK:
            self._execute(self.ok_action, result)
        if self.state == ALARM_INSUFFICIENT_DATA:
            self._execute(self.insufficient_data_action, result)

    def _execute(self, action, result):
        env = {}
        for k, v in result.iteritems():
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
