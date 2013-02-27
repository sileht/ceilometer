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


from ceilometer.openstack.common import log
from ceilometer.openstack.common import timeutils
from ceilometer.storage import models

LOG = log.getLogger(__name__)


class AggregatedMetric(models.Model):

    def __init__(self,
                 alarm_id,
                 id=None, unit="",
                 timestamp=None,
                 minimum=0.0, maximum=0.0, sum=0.0,
                 average=0.0, sample_count=0):

        timestamp = timestamp or timeutils.utcnow()
        super(AggregatedMetric, self).__init__(
            id=id,
            alarm_id=alarm_id,
            unit=unit,
            timestamp=timestamp,
            minimum=minimum,
            maximum=maximum,
            sum=sum,
            average=average,
            sample_count=sample_count)

    def update(self, meter):
        value = meter['counter_volume']
        if self.sample_count == 0:
            self.sample_count = 1
            self.minimum = self.minimum = self.sum = self.average = value
            self.unit = meter['counter_unit']
        else:
            self.sample_count += 1
            self.minimum = min(value, self.minimum)
            self.maximum = max(value, self.maximum)
            self.sum = value + self.sum
            self.average = self.sum / float(self.sample_count)
