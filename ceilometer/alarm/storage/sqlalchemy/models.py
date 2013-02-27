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
"""
SQLAlchemy models for nova data.
"""

import json
from urlparse import urlparse

from oslo.config import cfg

from sqlalchemy import Column, Integer, String, Boolean, Float, SmallInteger
from sqlalchemy import ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.types import TypeDecorator, VARCHAR

from ceilometer.openstack.common import timeutils

sql_opts = [
    cfg.StrOpt('alarm_mysql_engine',
               default='InnoDB',
               help='MySQL engine')
]

cfg.CONF.register_opts(sql_opts)


def table_args():
    engine_name = urlparse(cfg.CONF.alarm_database_connection).scheme
    if engine_name == 'mysql':
        return {'mysql_engine': cfg.CONF.alarm_mysql_engine,
                'mysql_charset': "utf8"}
    return None


class JSONEncodedDict(TypeDecorator):
    "Represents an immutable structure as a json-encoded string."

    impl = VARCHAR

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = json.loads(value)
        return value


class CeilometerBase(object):
    """Base class for Ceilometer Models."""
    __table_args__ = table_args()
    __table_initialized__ = False

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def update(self, values):
        """ Make the model object behave like a dict
        """
        for k, v in values.iteritems():
            setattr(self, k, v)

Base = declarative_base(cls=CeilometerBase)


class Alarm(Base):
    """Alarm data"""
    __tablename__ = 'alarm'
    id = Column(Integer, primary_key=True)
    enabled = Column(Boolean)
    name = Column(String(255))
    description = Column(String(255))
    timestamp = Column(DateTime, default=timeutils.utcnow)
    counter_name = Column(String(255))

    user_id = Column(String(255), ForeignKey('user.id'))
    project_id = Column(String(255), ForeignKey('project.id'))

    comparison_operator = Column(String(2))
    threshold = Column(Float)
    statistic = Column(String(255))
    evaluation_period = Column(Integer)
    aggregate_period = Column(Integer)

    state = Column(SmallInteger)
    state_timestamp = Column(DateTime, default=timeutils.utcnow)

    ok_actions = Column(JSONEncodedDict)
    alarm_actions = Column(JSONEncodedDict)
    insufficient_data_actions = Column(JSONEncodedDict)

    matching_metadata = Column(JSONEncodedDict)


class AggregatedMetric(Base):
    __tablename__ = 'aggregated_metric'
    id = Column(Integer, primary_key=True)
    alarm_id = Column(String(255), ForeignKey('alarm.id'))
    unit = Column(String(255))
    timestamp = Column(DateTime, default=timeutils.utcnow)
    minimum = Column(Float)
    maximum = Column(Float)
    average = Column(Float)
    sample_count = Column(Float)
    sum = Column(Float)


class User(Base):
    __tablename__ = 'user'
    id = Column(String(255), primary_key=True)
    alarms = relationship("Alarm", backref='user')


class Project(Base):
    __tablename__ = 'project'
    id = Column(String(255), primary_key=True)
    alarms = relationship("Alarm", backref='project')
