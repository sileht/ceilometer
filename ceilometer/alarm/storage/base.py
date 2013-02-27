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
"""Base classes for storage engines
"""

import abc

from ceilometer.openstack.common import log

LOG = log.getLogger(__name__)


class StorageEngine(object):
    """Base class for storage engines.
    """

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def register_opts(self, conf):
        """Register any configuration options used by this engine.
        """

    @abc.abstractmethod
    def get_connection(self, conf):
        """Return a Connection instance based on the configuration settings.
        """


class Connection(object):
    """Base class for storage system connections.
    """

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def __init__(self, conf):
        """Constructor"""

    @abc.abstractmethod
    def upgrade(self, version=None):
        """Migrate the database to `version` or the most recent version."""

    @abc.abstractmethod
    def alarm_list(self, name=None, user_id=None,
                   project=None, enabled=True):
        """Yields a lists of alarms that match filters
        """

    @abc.abstractmethod
    def alarm_get(self, alarm_id):
        """Return alarm data.
        """

    @abc.abstractmethod
    def alarm_update(self, alarm):
        """update alarm
        """

    @abc.abstractmethod
    def alarm_add(self, alarm):
        """add a alarm
        """

    @abc.abstractmethod
    def alarm_delete(self, alarm_id):
        """Delete a alarm
        """

    @abc.abstractmethod
    def aggregated_metric_add(self, aggregated_metric):
        """Add an aggregate
        """

    @abc.abstractmethod
    def aggregated_metric_get(self, aggregated_metric_id):
        """Return an aggregate
        """

    @abc.abstractmethod
    def aggregated_metric_list(self, alarm_id):
        """Return a list of aggregate ID
        """

    @abc.abstractmethod
    def aggregated_metric_update(self, aggregated_metric):
        """Update data of a aggregate
        """

    def aggregated_metric_delete(self, aggregated_metric_id):
        """delete aggregated data
        """

    @abc.abstractmethod
    def clear(self):
        """Clear database."""
