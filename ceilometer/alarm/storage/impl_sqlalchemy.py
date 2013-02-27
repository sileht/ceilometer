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

from sqlalchemy.orm import exc

from ceilometer import exception
from ceilometer.openstack.common import log
from ceilometer.alarm.alarm import Alarm as AlarmModel
from ceilometer.alarm.aggregated_metric \
    import AggregatedMetric as AggregatedMetricModel
from ceilometer.alarm.storage import base
from ceilometer.alarm.storage.sqlalchemy import migration
from ceilometer.alarm.storage.sqlalchemy.models import User, Project
from ceilometer.alarm.storage.sqlalchemy.models import Alarm
from ceilometer.alarm.storage.sqlalchemy.models import AggregatedMetric
from ceilometer.alarm.storage.sqlalchemy.models import Base
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

           metadata: list of tuple (CW dimensions) (String(255)) (JSON)
           aggregated_metrics: aggregated metrics
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
     - aggregated_metric
       - a already calculated aggregate of a metric
       - { id : aggregate id (Integer)
           alarm: the associated alarm (->alarm.id) (String(255))
           unit : the unit of the metric (String(255)) or (Enum)
           timestamp : create datetime (Datetime)
           minimum : the minimum value of the metric since 'timestamp' (Float)
           maximum : the maximum value of the metric since 'timestamp' (Float)
           average : the average value of the metric since 'timestamp' (Float)
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
        LOG.info('connecting to %s', conf.alarm_database_connection)
        self.session = self._get_connection(conf)
        return

    def upgrade(self, version=None):
        migration.db_sync(self.session.get_bind(), version=version)

    def clear(self):
        engine = self.session.get_bind()
        for table in reversed(Base.metadata.sorted_tables):
            engine.execute(table.delete())

    def _get_connection(self, conf):
        """Return a connection to the database.
        """
        return sqlalchemy_session.get_session()

    def _row_to_aggregated_metric_model(self, row):
        return AggregatedMetricModel(id=row.id,
                                     alarm_id=row.alarm_id,
                                     unit=row.unit,
                                     timestamp=row.timestamp,
                                     minimum=row.minimum,
                                     maximum=row.maximum,
                                     average=row.average,
                                     sum=row.sum,
                                     sample_count=row.sample_count
                                     )

    def _aggregated_metric_model_to_row(self, aggregate, row=None):
        if row is None:
            row = AggregatedMetric()
        row.update(aggregate.as_dict())
        return row

    def _row_to_alarm_model(self, row):
        return AlarmModel(id=row.id,
                          enabled=row.enabled,
                          name=row.name,
                          description=row.description,
                          timestamp=row.timestamp,
                          counter_name=row.counter_name,
                          user_id=row.user_id,
                          project_id=row.project_id,
                          comparison_operator=row.comparison_operator,
                          threshold=row.threshold,
                          statistic=row.statistic,
                          evaluation_period=row.evaluation_period,
                          aggregate_period=row.aggregate_period,
                          state=row.state,
                          state_timestamp=row.state_timestamp,
                          ok_actions=row.ok_actions,
                          alarm_actions=row.alarm_actions,
                          insufficient_data_actions=
                          row.insufficient_data_actions,
                          matching_metadata=row.matching_metadata)

    def _alarm_model_to_row(self, alarm, row=None):
        if row is None:
            row = Alarm()
        row.update(alarm.as_dict())
        return row

    def alarm_list(self, name=None, user_id=None,
                   project_id=None, enabled=None):
        """Return an iterable of alarm model"

        :param user: Optional ID for user that owns the resource.
        :param project: Optional ID for project that owns the resource.
        :param enabled: Optional boolean to list disable alarm
        """
        query = model_query(Alarm.id, session=self.session)

        if name is not None:
            query = query.filter(Alarm.name == name)
        if enabled is not None:
            query = query.filter(Alarm.enabled == enabled)
        if user_id is not None:
            query = query.filter(Alarm.user_id == user_id)
        if project_id is not None:
            query = query.filter(Alarm.project_id == project_id)

        return (x[0] for x in query.all())

    def _raw_alarm_get(self, alarm_id):
        """Return row alarm information.

        :param id: ID of the alarm
        """
        query = model_query(Alarm, session=self.session)
        query = query.filter(Alarm.id == alarm_id)

        try:
            result = query.one()
        except exc.NoResultFound:
            raise exception.AlarmNotFound(alarm=alarm_id)

        return result

    def alarm_get(self, alarm_id):
        """Return alarm information.

        :param id: ID of the alarm
        """
        return self._row_to_alarm_model(self._raw_alarm_get(alarm_id))

    def alarm_update(self, alarm):
        """update alarm

        :param name: the alarm
        """

        alarm_row = self.session.merge(Alarm(id=str(alarm.id)))
        self._alarm_model_to_row(alarm, alarm_row)
        self.session.flush()

    def alarm_add(self, alarm):
        """add a alarm

        :param data: alarm data
        """

        self.session.merge(User(id=str(alarm.user_id)))
        self.session.merge(Project(id=str(alarm.project_id)))

        alarm_row = self._alarm_model_to_row(alarm)
        self.session.add(alarm_row)
        self.session.flush()

        return self._row_to_alarm_model(alarm_row)

    def alarm_delete(self, alarm_id):
        """Delete a alarm and its aggregated_metrics

        :param id: ID of the alarm
        """
        self.session.delete(self._raw_alarm_get(alarm_id))

        query = model_query(Alarm, session=self.session)
        query = query.filter(Alarm.id == alarm_id)
        query.delete()

    def aggregated_metric_get(self, aggregated_metric_id):
        """Return a aggregate

        :param aggregated_metric_id: ID of the aggregated_metric
        """
        query = model_query(AggregatedMetric, session=self.session)
        query = query.filter(AggregatedMetric.id == aggregated_metric_id)

        try:
            result = query.one()
        except exc.NoResultFound:
            raise exception.AggregateNotFound(
                aggregate=aggregated_metric_id)

        return self._row_to_aggregated_metric_model(result)

    def aggregated_metric_list(self, alarm_id):
        """Return a sorted (by timestamp) list of aggregate ID

        :param id: ID of the alarm
        :param limit: number of result to return
        :param start: oldest aggregate to return
        """
        query = model_query(AggregatedMetric.id, session=self.session)
        query = query.filter(AggregatedMetric.alarm_id == alarm_id)
        query = query.order_by(AggregatedMetric.timestamp.desc())

        return (x[0] for x in query.all())

    def aggregated_metric_update(self, aggregated_metric):
        aggregated_metric_row = self.session.merge(AggregatedMetric(
            id=str(aggregated_metric.id)))
        self._aggregated_metric_model_to_row(aggregated_metric,
                                             aggregated_metric_row)
        self.session.flush()

    def aggregated_metric_delete(self, aggregated_metric_id):
        query = model_query(AggregatedMetric, session=self.session)
        query = query.filter(AggregatedMetric.id == aggregated_metric_id)
        return query.delete()

    def aggregated_metric_add(self, aggregated_metric):
        """add a aggregated_metric

        :param data: aggregated_metric data
        """

        aggregated_metric_row = self._aggregated_metric_model_to_row(
            aggregated_metric)
        self.session.add(aggregated_metric_row)
        self.session.flush()

        return self._row_to_aggregated_metric_model(aggregated_metric_row)


def model_query(*args, **kwargs):
    """Query helper

    :param session: if present, the session to use
    """
    session = kwargs.get('session') or sqlalchemy_session.get_session()
    query = session.query(*args)
    return query
