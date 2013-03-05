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
"""SQLAlchemy alarm storage backend
"""

from __future__ import absolute_import

import copy

from sqlalchemy.orm import exc

from ceilometer import exception
from ceilometer.openstack.common import log
from ceilometer.openstack.common import timeutils
from ceilometer.alarm.storage import base
from ceilometer.alarm.storage.sqlalchemy import migration
from ceilometer.alarm.storage.sqlalchemy.models import User, Project
from ceilometer.alarm.storage.sqlalchemy.models import Alarm, AlarmMetadata
from ceilometer.alarm.storage.sqlalchemy.models import AggregatedMetric
import ceilometer.alarm.storage.sqlalchemy.session as sqlalchemy_session

LOG = log.getLogger(__name__)


class SQLAlchemyStorage(base.StorageEngine):
    """Put the data into a SQLAlchemy database

    Tables::
     - user
       - { id: user uuid }
     - project
       - { id: project uuid }
     - alarm
       - the alarm description
       - { id: alarm id (integer)
           enabled: alarm is enabled (bool)
           name: alarm name (String(255))
           description: alarm description (String(255))
           timestamp: alarm last update datetime (Datetime)

           counter_name: alarm counter (String(255))

           user_id: user alarm owner uuid  (->user.id) (String(255))
           project_id: project alarm owner uuid (->project.id) (String(255))

           comparison_operator: alarm comparison operator (String(2))
           threshold: alarm threshold (Float)
           statistic: alarm statistic (String(4)) or (Enum)

           evaluation_period: number of aggregate_period to evaluate (Integer)
           aggregate_period: period in seconds of a aggregate (Integer)

           alarm_metadatas: alarm metadata used to match a counter
               (CW dimensions) (a sqlachemy proxy of metadata table)
           aggregate_metrics: aggregated metrics
                              (a sqlachemy proxy of aggregated_metric table)

           state: alarm state (SmallInteger) or (Enum)
           state_timestamp: alarm state last update datetime (Datetime)

           ok_actions: list of action to do when
               "ok" state is raised (String(255)) (JSON)
           alarm_actions: list of action to do when
               "alarm" state is raised (String(255)) (JSON)
           insufficient_data_actions: list of action to do when
               "insufficient data" state is raised (String(255)) (JSON)
           }
     - alarm_metadata
       - a alarm metadata
       - { alarm: the associated alarm (->alarm.id) (String(255))
           name: the metadata name (String(255))
           value: the metadata value (String(255))
         }
     - aggregated_metric
       - a already calculated aggregate of a metric
       - { id : aggregate id (Integer)
           alarm: the associated alarm (->alarm.id) (String(255))
           unit : the unit of the metric (String(255)) or (Enum)
           timestamp : create datetime (Datetime)
           minimum : the minimum value of the metric since 'timestamp' (Float)
           maximum : the maximum value of the metric since 'timestamp' (Float)
           sum : the sum of each counter of the metric
                 since 'timestamp' (Float)
           sample_count : the number of counter aggregated
                          since 'timestamp' (Float)
           }
    """

    OPTIONS = []

    def register_opts(self, conf):
        """Register any configuration options used by this engine.
        """
        conf.register_opts(self.OPTIONS)

    def get_connection(self, conf):
        """Return a Connection instance based on the configuration settings.
        """
        return Connection(conf)


class Connection(base.Connection):
    """SqlAlchemy connection.
    """

    def __init__(self, conf):
        LOG.info('connecting to %s', conf.database_alarm_connection)
        self.session = self._get_connection(conf)
        return

    def upgrade(self, version=None):
        migration.db_sync(self.session.get_bind(), version=version)

    def _get_connection(self, conf):
        """Return a connection to the database.
        """
        return sqlalchemy_session.get_session()

    def alarm_list(self, name=None, counter_name=None, user_id=None,
                   project_id=None, enabled=True, metaquery=[]):
        """Return an iterable of dictionaries containing alarm information.

        note(sileht): if metaquery is not empty this function return
        alarm that match the metadata and the alarm without metadata.
        This is the desired behavior

        :param user: Optional ID for user that owns the resource.
        :param project: Optional ID for project that owns the resource.
        :param metaquery: Optional dict with metadata to match on.
        """
        query = model_query(Alarm, session=self.session)
        query = query.options(
            sqlalchemy_session.sqlalchemy.orm.joinedload('alarm_metadatas'))

        if name is not None:
            query = query.filter(Alarm.name == name)
        if counter_name is not None:
            query = query.filter(Alarm.counter_name == counter_name)
        if enabled is not None:
            query = query.filter(Alarm.enabled == enabled)
        if user_id is not None:
            query = query.filter(Alarm.user_id == user_id)
        if project_id is not None:
            query = query.filter(Alarm.project_id == project_id)

        #TODO(sileht): smartest match
        #      to allow have many user_id or instance_id or ...
        for k, v in metaquery:
            query = query.filter(AlarmMetadata.name == k)
            query = query.filter(AlarmMetadata.value == v)

        for alarm in query.all():
            yield row2dict(alarm)

    def alarm_get(self, alarm_id):
        """Return alarm information.

        :param id: ID of the alarm
        """
        query = model_query(Alarm, session=self.session)
        query = query.filter(Alarm.id == alarm_id)
        query = query.options(
            sqlalchemy_session.sqlalchemy.orm.joinedload('alarm_metadatas'))

        try:
            result = query.one()
        except exc.NoResultFound:
            raise exception.AlarmNotFound(alarm=alarm_id)

        return row2dict(result)

    def alarm_update_state(self, alarm_id, state, timestamp):
        """update alarm state

        :param name: ID of the alarm
        :param state: new state of the alarm
        :param timestamp: last update of the alarm state
        """

        alarm = self.session.merge(Alarm(id=str(alarm_id)))
        alarm.update({
            'state': state,
            'state_timestamp': timestamp,
        })
        return row2dict(alarm)

    def alarm_add(self, data):
        """add a alarm

        :param data: alarm data
        """

        if data['user_id']:
            self.session.merge(User(id=str(data['user_id'])))

        if data['project_id']:
            self.session.merge(Project(id=str(data['project_id'])))

        data.update({
            'timestamp': timeutils.utcnow(),
            'state_timestamp': timeutils.utcnow(),
        })

        alarm_metadatas = data["alarm_metadatas"]
        del data["alarm_metadatas"]

        alarm = Alarm(**data)
        self.session.add(alarm)
        self.session.flush()

        for k, v in alarm_metadatas:
            am_data = {'alarm_id': alarm.id, 'name': k, 'value': v}
            self.session.add(AlarmMetadata(**am_data))
        self.session.flush()

        return row2dict(alarm)

    def alarm_delete(self, alarm_id):
        """Delete a alarm

        :param id: ID of the alarm
        """
        query = model_query(Alarm, session=self.session)
        query = query.filter(Alarm.id == alarm_id)
        query = query.options(
            sqlalchemy_session.sqlalchemy.orm.joinedload('alarm'))

        query.delete()

    def aggregated_metric_get(self, aggregate_metric_id):
        """Return a aggregate

        :param aggregate_metric_id: ID of the aggregate_metric
        """
        query = model_query(AggregatedMetric, session=self.session)
        query = query.filter(AggregatedMetric.id == aggregate_metric_id)

        try:
            result = query.one()
        except exc.NoResultFound:
            raise exception.AggregateNotFound(aggregate=aggregate_metric_id)

        return row2dict(result)

    def aggregated_metric_list(self, alarm_id, limit=None, start=None):
        """Return a list of aggregate

        :param id: ID of the alarm
        :param limit: number of result to return
        :param start: oldest aggregate to return
        """
        query = model_query(AggregatedMetric, session=self.session)
        query = query.filter(AggregatedMetric.alarm_id == alarm_id)
        if start is not None:
            query = query.filter(AggregatedMetric.timestamp >= start)

        query = query.order_by(AggregatedMetric.timestamp.desc())
        if limit is not None:
            query = query.limit(limit)

        for aggregate in query.all():
            yield row2dict(aggregate)

    def aggregated_metric_update(self, aggregate_metric_id, data):
        """Update data of a aggregate

        :param aggregate_metric_id: ID of the aggregate
        :param data: data to update (dict)
        """
        if aggregate_metric_id is None:
            aggregate = AggregatedMetric(**data)
            self.session.add(aggregate)
            self.session.flush()
        else:
            aggregate = self.session.merge(
                AggregatedMetric(id=str(aggregate_metric_id)))
            aggregate.update(data)
        return row2dict(aggregate)


def model_query(*args, **kwargs):
    """Query helper

    :param session: if present, the session to use
    """
    session = kwargs.get('session') or sqlalchemy_session.get_session()
    query = session.query(*args)
    return query


def row2dict(row):
    """Convert row to a dict and remove unwanted field
    """
    d = copy.copy(row.__dict__)
    for k in d.keys():
        if k.startswith('_'):
            del d[k]

    if 'alarm_metadatas' in d:
        alarm_metadatas = d.get('alarm_metadatas', [])
        d['alarm_metadatas'] = []
        for m in alarm_metadatas:
            d['alarm_metadatas'].append((m['name'], m['value']))

    return d
