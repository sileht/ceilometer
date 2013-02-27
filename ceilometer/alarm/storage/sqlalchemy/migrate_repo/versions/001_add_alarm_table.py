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

from sqlalchemy import MetaData, Table, Column
from sqlalchemy import Boolean, Integer, SmallInteger, String, DateTime, Float

meta = MetaData()

alarm = Table(
    'alarm', meta,
    Column('id', Integer, primary_key=True, index=True),
    Column('enabled', Boolean),
    Column('name', String(255)),
    Column('description', String(255)),
    Column('timestamp', DateTime(timezone=False)),
    Column('counter_name', String(255), index=True),
    Column('user_id', String(255), index=True),
    Column('project_id', String(255), index=True),
    Column('comparison_operator', String(2)),
    Column('threshold', Float),
    Column('statistic', String(255)),
    Column('evaluation_period', Integer),
    Column('aggregate_period', Integer),
    Column('state', SmallInteger),
    Column('state_timestamp', DateTime(timezone=False)),
    Column('ok_actions', String(5000)),
    Column('alarm_actions', String(5000)),
    Column('insufficient_data_actions', String(5000)),
    Column('matching_metadata', String(5000))
)

aggregated_metric = Table(
    'aggregated_metric', meta,
    Column('id', Integer, primary_key=True, index=True),
    Column('alarm_id', String(255), index=True),
    Column('unit', String(255)),
    Column('timestamp', DateTime(timezone=False)),
    Column('minimum', Float),
    Column('maximum', Float),
    Column('sum', Float),
    Column('average', Float),
    Column('sample_count', Float),

)

user = Table(
    'user', meta,
    Column('id', String(255), primary_key=True, index=True),
)

project = Table(
    'project', meta,
    Column('id', String(255), primary_key=True, index=True),
)

tables = [alarm, aggregated_metric, user, project]


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    for i in sorted(tables):
        i.create()


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    for i in sorted(tables, reverse=True):
        i.drop()
