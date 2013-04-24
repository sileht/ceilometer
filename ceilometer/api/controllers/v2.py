# -*- encoding: utf-8 -*-
#
# Copyright © 2012 New Dream Network, LLC (DreamHost)
#
# Author: Doug Hellmann <doug.hellmann@dreamhost.com>
#         Angus Salkeld <asalkeld@redhat.com>
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
"""Version 2 of the API.
"""

# [GET ] / -- information about this version of the API
#
# [GET   ] /resources -- list the resources
# [GET   ] /resources/<resource> -- information about the resource
# [GET   ] /meters -- list the meters
# [POST  ] /meters -- insert a new sample (and meter/resource if needed)
# [GET   ] /meters/<meter> -- list the samples for this meter
# [PUT   ] /meters/<meter> -- update the meter (not the samples)
# [DELETE] /meters/<meter> -- delete the meter and samples
# [GET   ] /alarms -- list the alarms
# [POST  ] /alarms -- insert a new alarm
# [GET   ] /alarms/<alarm> -- show the definition of a alarm
# [PUT   ] /alarms/<alarm> -- update the definition of a alarm
# [DELETE] /alarms/<alarm> -- delete a alarm
#

import datetime
import inspect
import pecan
from pecan import rest

import wsme
import wsmeext.pecan as wsme_pecan
from wsme import types as wtypes

from oslo.config import cfg

from ceilometer import exception
from ceilometer import policy
from ceilometer.openstack.common import log
from ceilometer.openstack.common import timeutils
from ceilometer.openstack.common import rpc
from ceilometer.openstack.common import context
from ceilometer.openstack.common.gettextutils import _
from ceilometer import storage
from ceilometer.alarm.alarm import Alarm as AlarmModel
from ceilometer.alarm.alarm import STATE_MAP

LOG = log.getLogger(__name__)

cfg.CONF.import_opt("alarms_topic", "ceilometer.alarm.service")

operation_kind = wtypes.Enum(str, 'lt', 'le', 'eq', 'ne', 'ge', 'gt')


class _Base(wtypes.Base):

    @classmethod
    def from_db_model(cls, m):
        return cls(**(m.as_dict()))

    def as_dict(self, db_model):
        valid_keys = inspect.getargspec(db_model.__init__)[0]
        if 'self' in valid_keys:
            valid_keys.remove('self')

        return dict((k, getattr(self, k))
                    for k in valid_keys
                    if hasattr(self, k) and
                    getattr(self, k) != wsme.Unset)


class Query(_Base):
    """Query filter.
    """

    _op = None  # provide a default

    def get_op(self):
        return self._op or 'eq'

    def set_op(self, value):
        self._op = value

    field = wtypes.text
    "The name of the field to test"

    #op = wsme.wsattr(operation_kind, default='eq')
    # this ^ doesn't seem to work.
    op = wsme.wsproperty(operation_kind, get_op, set_op)
    "The comparison operator. Defaults to 'eq'."

    value = wtypes.text
    "The value to compare against the stored data"

    def __repr__(self):
        # for logging calls
        return '<Query %r %s %r>' % (self.field, self.op, self.value)

    @classmethod
    def sample(cls):
        return cls(field='resource_id',
                   op='eq',
                   value='bd9431c1-8d69-4ad3-803a-8d4a6b89fd36',
                   )


def _query_to_kwargs(query, db_func):
    # TODO(dhellmann): This function needs tests of its own.
    valid_keys = inspect.getargspec(db_func)[0]
    if 'self' in valid_keys:
        valid_keys.remove('self')
    translation = {'user_id': 'user',
                   'project_id': 'project',
                   'resource_id': 'resource'}
    stamp = {}
    trans = {}
    metaquery = {}
    for i in query:
        if i.field == 'timestamp':
            # FIXME(dhellmann): This logic is not consistent with the
            # way the timestamps are treated inside the mongo driver
            # (the end timestamp is always tested using $lt). We
            # should just pass a single timestamp through to the
            # storage layer with the operator and let the storage
            # layer use that operator.
            if i.op in ('lt', 'le'):
                stamp['end_timestamp'] = i.value
            elif i.op in ('gt', 'ge'):
                stamp['start_timestamp'] = i.value
            else:
                LOG.warn('_query_to_kwargs ignoring %r unexpected op %r"' %
                         (i.field, i.op))
        else:
            if i.op != 'eq':
                LOG.warn('_query_to_kwargs ignoring %r unimplemented op %r' %
                         (i.field, i.op))
            elif i.field == 'search_offset':
                stamp['search_offset'] = i.value
            elif i.field.startswith('metadata.'):
                metaquery[i.field] = i.value
            else:
                trans[translation.get(i.field, i.field)] = i.value

    kwargs = {}
    if metaquery and 'metaquery' in valid_keys:
        kwargs['metaquery'] = metaquery
    if stamp:
        q_ts = _get_query_timestamps(stamp)
        if 'start' in valid_keys:
            kwargs['start'] = q_ts['query_start']
            kwargs['end'] = q_ts['query_end']
        elif 'start_timestamp' in valid_keys:
            kwargs['start_timestamp'] = q_ts['query_start']
            kwargs['end_timestamp'] = q_ts['query_end']
        else:
            raise wsme.exc.UnknownArgument('timestamp',
                                           "not valid for this resource")

    if trans:
        for k in trans:
            if k not in valid_keys:
                raise wsme.exc.UnknownArgument(i.field,
                                               "unrecognized query field")
            kwargs[k] = trans[k]

    return kwargs


def _get_query_timestamps(args={}):
    """Return any optional timestamp information in the request.

    Determine the desired range, if any, from the GET arguments. Set
    up the query range using the specified offset.

    [query_start ... start_timestamp ... end_timestamp ... query_end]

    Returns a dictionary containing:

    query_start: First timestamp to use for query
    start_timestamp: start_timestamp parameter from request
    query_end: Final timestamp to use for query
    end_timestamp: end_timestamp parameter from request
    search_offset: search_offset parameter from request

    """
    search_offset = int(args.get('search_offset', 0))

    start_timestamp = args.get('start_timestamp')
    if start_timestamp:
        start_timestamp = timeutils.parse_isotime(start_timestamp)
        start_timestamp = start_timestamp.replace(tzinfo=None)
        query_start = (start_timestamp -
                       datetime.timedelta(minutes=search_offset))
    else:
        query_start = None

    end_timestamp = args.get('end_timestamp')
    if end_timestamp:
        end_timestamp = timeutils.parse_isotime(end_timestamp)
        end_timestamp = end_timestamp.replace(tzinfo=None)
        query_end = end_timestamp + datetime.timedelta(minutes=search_offset)
    else:
        query_end = None

    return {'query_start': query_start,
            'query_end': query_end,
            'start_timestamp': start_timestamp,
            'end_timestamp': end_timestamp,
            'search_offset': search_offset,
            }


def _flatten_metadata(metadata):
    """Return flattened resource metadata without nested structures
    and with all values converted to unicode strings.
    """
    if metadata:
        return dict((k, unicode(v))
                    for k, v in metadata.iteritems()
                    if type(v) not in set([list, dict, set]))
    return {}


class Sample(_Base):
    """A single measurement for a given meter and resource.
    """

    source = wtypes.text
    "An identity source ID"

    counter_name = wtypes.text
    "The name of the meter"
    # FIXME(dhellmann): Make this meter_name?

    counter_type = wtypes.text
    "The type of the meter (see :ref:`measurements`)"
    # FIXME(dhellmann): Make this meter_type?

    counter_unit = wtypes.text
    "The unit of measure for the value in counter_volume"
    # FIXME(dhellmann): Make this meter_unit?

    counter_volume = float
    "The actual measured value"

    user_id = wtypes.text
    "The ID of the user who last triggered an update to the resource"

    project_id = wtypes.text
    "The ID of the project or tenant that owns the resource"

    resource_id = wtypes.text
    "The ID of the :class:`Resource` for which the measurements are taken"

    timestamp = datetime.datetime
    "UTC date and time when the measurement was made"

    resource_metadata = {wtypes.text: wtypes.text}
    "Arbitrary metadata associated with the resource"

    message_id = wtypes.text
    "A unique identifier for the sample"

    def __init__(self, counter_volume=None, resource_metadata={}, **kwds):
        if counter_volume is not None:
            counter_volume = float(counter_volume)
        resource_metadata = _flatten_metadata(resource_metadata)
        super(Sample, self).__init__(counter_volume=counter_volume,
                                     resource_metadata=resource_metadata,
                                     **kwds)

    @classmethod
    def sample(cls):
        return cls(source='openstack',
                   counter_name='instance',
                   counter_type='gauge',
                   counter_unit='instance',
                   counter_volume=1,
                   resource_id='bd9431c1-8d69-4ad3-803a-8d4a6b89fd36',
                   project_id='35b17138-b364-4e6a-a131-8f3099c5be68',
                   user_id='efd87807-12d2-4b38-9c70-5f5c2ac427ff',
                   timestamp=datetime.datetime.utcnow(),
                   metadata={'name1': 'value1',
                             'name2': 'value2'},
                   message_id='5460acce-4fd6-480d-ab18-9735ec7b1996',
                   )


class Statistics(_Base):
    """Computed statistics for a query.
    """

    min = float
    "The minimum volume seen in the data"

    max = float
    "The maximum volume seen in the data"

    avg = float
    "The average of all of the volume values seen in the data"

    sum = float
    "The total of all of the volume values seen in the data"

    count = int
    "The number of samples seen"

    duration = float
    "The difference, in minutes, between the oldest and newest timestamp"

    duration_start = datetime.datetime
    "UTC date and time of the earliest timestamp, or the query start time"

    duration_end = datetime.datetime
    "UTC date and time of the oldest timestamp, or the query end time"

    period = int
    "The difference, in seconds, between the period start and end"

    period_start = datetime.datetime
    "UTC date and time of the period start"

    period_end = datetime.datetime
    "UTC date and time of the period end"

    def __init__(self, start_timestamp=None, end_timestamp=None, **kwds):
        super(Statistics, self).__init__(**kwds)
        self._update_duration(start_timestamp, end_timestamp)

    def _update_duration(self, start_timestamp, end_timestamp):
        # "Clamp" the timestamps we return to the original time
        # range, excluding the offset.
        if (start_timestamp and
                self.duration_start and
                self.duration_start < start_timestamp):
            self.duration_start = start_timestamp
            LOG.debug('clamping min timestamp to range')
        if (end_timestamp and
                self.duration_end and
                self.duration_end > end_timestamp):
            self.duration_end = end_timestamp
            LOG.debug('clamping max timestamp to range')

        # If we got valid timestamps back, compute a duration in minutes.
        #
        # If the min > max after clamping then we know the
        # timestamps on the samples fell outside of the time
        # range we care about for the query, so treat them as
        # "invalid."
        #
        # If the timestamps are invalid, return None as a
        # sentinal indicating that there is something "funny"
        # about the range.
        if (self.duration_start and
                self.duration_end and
                self.duration_start <= self.duration_end):
            self.duration = timeutils.delta_seconds(self.duration_start,
                                                    self.duration_end)
        else:
            self.duration_start = self.duration_end = self.duration = None

    @classmethod
    def sample(cls):
        return cls(min=1,
                   max=9,
                   avg=4.5,
                   sum=45,
                   count=10,
                   duration_start=datetime.datetime(2013, 1, 4, 16, 42),
                   duration_end=datetime.datetime(2013, 1, 4, 16, 47),
                   period=7200,
                   period_start=datetime.datetime(2013, 1, 4, 16, 00),
                   period_end=datetime.datetime(2013, 1, 4, 18, 00),
                   )


class MeterController(rest.RestController):
    """Manages operations on a single meter.
    """
    _custom_actions = {
        'statistics': ['GET'],
    }

    def __init__(self, meter_id):
        pecan.request.context['meter_id'] = meter_id
        self._id = meter_id

    @wsme_pecan.wsexpose([Sample], [Query])
    def get_all(self, q=[]):
        """Return samples for the meter.

        :param q: Filter rules for the data to be returned.
        """
        kwargs = _query_to_kwargs(q, storage.EventFilter.__init__)
        kwargs['meter'] = self._id
        f = storage.EventFilter(**kwargs)
        return [Sample.from_db_model(e)
                for e in pecan.request.storage_conn.get_samples(f)
                ]

    @wsme_pecan.wsexpose([Statistics], [Query], int)
    def statistics(self, q=[], period=None):
        """Computes the statistics of the samples in the time range given.

        :param q: Filter rules for the data to be returned.
        :param period: Returned result will be an array of statistics for a
                       period long of that number of seconds.

        """
        kwargs = _query_to_kwargs(q, storage.EventFilter.__init__)
        kwargs['meter'] = self._id
        f = storage.EventFilter(**kwargs)
        computed = pecan.request.storage_conn.get_meter_statistics(f, period)
        LOG.debug('computed value coming from %r', pecan.request.storage_conn)
        # Find the original timestamp in the query to use for clamping
        # the duration returned in the statistics.
        start = end = None
        for i in q:
            if i.field == 'timestamp' and i.op in ('lt', 'le'):
                end = timeutils.parse_isotime(i.value).replace(tzinfo=None)
            elif i.field == 'timestamp' and i.op in ('gt', 'ge'):
                start = timeutils.parse_isotime(i.value).replace(tzinfo=None)

        return [Statistics(start_timestamp=start,
                           end_timestamp=end,
                           **c.as_dict())
                for c in computed]


class Meter(_Base):
    """One category of measurements.
    """

    name = wtypes.text
    "The unique name for the meter"

    # FIXME(dhellmann): Make this an enum?
    type = wtypes.text
    "The meter type (see :ref:`measurements`)"

    unit = wtypes.text
    "The unit of measure"

    resource_id = wtypes.text
    "The ID of the :class:`Resource` for which the measurements are taken"

    project_id = wtypes.text
    "The ID of the project or tenant that owns the resource"

    user_id = wtypes.text
    "The ID of the user who last triggered an update to the resource"

    @classmethod
    def sample(cls):
        return cls(name='instance',
                   type='gauge',
                   unit='instance',
                   resource_id='bd9431c1-8d69-4ad3-803a-8d4a6b89fd36',
                   project_id='35b17138-b364-4e6a-a131-8f3099c5be68',
                   user_id='efd87807-12d2-4b38-9c70-5f5c2ac427ff',
                   )


class MetersController(rest.RestController):
    """Works on meters."""

    @pecan.expose()
    def _lookup(self, meter_id, *remainder):
        return MeterController(meter_id), remainder

    @wsme_pecan.wsexpose([Meter], [Query])
    def get_all(self, q=[]):
        """Return all known meters, based on the data recorded so far.

        :param q: Filter rules for the meters to be returned.
        """
        kwargs = _query_to_kwargs(q, pecan.request.storage_conn.get_meters)
        return [Meter.from_db_model(m)
                for m in pecan.request.storage_conn.get_meters(**kwargs)]


class Resource(_Base):
    """An externally defined object for which samples have been received.
    """

    resource_id = wtypes.text
    "The unique identifier for the resource"

    project_id = wtypes.text
    "The ID of the owning project or tenant"

    user_id = wtypes.text
    "The ID of the user who created the resource or updated it last"

    timestamp = datetime.datetime
    "UTC date and time of the last update to any meter for the resource"

    metadata = {wtypes.text: wtypes.text}
    "Arbitrary metadata associated with the resource"

    def __init__(self, metadata={}, **kwds):
        metadata = _flatten_metadata(metadata)
        super(Resource, self).__init__(metadata=metadata, **kwds)

    @classmethod
    def sample(cls):
        return cls(resource_id='bd9431c1-8d69-4ad3-803a-8d4a6b89fd36',
                   project_id='35b17138-b364-4e6a-a131-8f3099c5be68',
                   user_id='efd87807-12d2-4b38-9c70-5f5c2ac427ff',
                   timestamp=datetime.datetime.utcnow(),
                   metadata={'name1': 'value1',
                             'name2': 'value2'},
                   )


class ResourcesController(rest.RestController):
    """Works on resources."""

    @wsme_pecan.wsexpose(Resource, unicode)
    def get_one(self, resource_id):
        """Retrieve details about one resource.

        :param resource_id: The UUID of the resource.
        """
        r = list(pecan.request.storage_conn.get_resources(
                 resource=resource_id))[0]
        return Resource.from_db_model(r)

    @wsme_pecan.wsexpose([Resource], [Query])
    def get_all(self, q=[]):
        """Retrieve definitions of all of the resources.

        :param q: Filter rules for the resources to be returned.
        """
        kwargs = _query_to_kwargs(q, pecan.request.storage_conn.get_resources)
        resources = [
            Resource.from_db_model(r)
            for r in pecan.request.storage_conn.get_resources(**kwargs)]
        return resources


class Alarm(_Base):
    """One category of measurements.
    """

    id = int
    "The ID of the alarm"

    name = wtypes.text
    "The name for the alarm"

    description = wtypes.text
    "The description of the alarm"

    counter_name = wtypes.text
    "The name of counter"

    project_id = wtypes.text
    "The ID of the project or tenant that owns the alarm"

    user_id = wtypes.text
    "The ID of the user who last triggered an update to the alarm"

    comparison_operator = wtypes.Enum(str, 'lt', 'le', 'eq', 'ne', 'ge', 'gt')
    "The comparaison of the alarm threshold"

    threshold = float
    "The threshold of the alarm"

    statistic = wtypes.Enum(str, 'maximum', 'minimum', 'average', 'sum',
                            'sample_count')
    "The statistic to compare to the threshold"

    enabled = bool
    "This alarm is enabled?"

    evaluation_period = float
    "The number of period to evaluate with the threshold"

    aggregate_period = float
    "The time range of a aggregate of metric to evaluate with the threshold"

    timestamp = datetime.datetime
    "The date of the last alarm definition update"

    state = wtypes.Enum(str, 'ok', 'alarm', 'insufficient data')
    "The state offset the alarm"

    state_timestamp = datetime.datetime
    "The date of the last alarm state changed"

    ok_actions = [wtypes.text]
    "The actions to do when alarm state change to ok"

    alarm_actions = [wtypes.text]
    "The actions to do when alarm state change to alarm"

    insufficient_data_actions = [wtypes.text]
    "The actions to do when alarm state change to insufficient data"

    matching_metadata = {wtypes.text: wtypes.text}
    "The matching_metadata of the alarm"

    #http://pythonhosted.org/WSME/
    #http://pythonhosted.org/WSME/types.html#native-types

    def __init__(self, **kwargs):
        # Use user friendly name for state
        if 'state' in kwargs:
            kwargs['state'] = STATE_MAP[kwargs['state']]
        super(Alarm, self).__init__(**kwargs)

    @classmethod
    def sample(cls):
        return cls(id=None,
                   name="SwiftObjectAlarm",
                   description="A alarm",
                   counter_name="storage.objects",
                   comparison_operator="gt",
                   threshold=200,
                   statistic="average",
                   user_id="c96c887c216949acbdfbd8b494863567",
                   project_id="c96c887c216949acbdfbd8b494863567",
                   evaluation_period=240.0,
                   aggregate_period=2,
                   enabled=True,
                   timestamp=datetime.datetime.utcnow(),
                   state=0,
                   state_timestamp=datetime.datetime.utcnow(),
                   ok_actions=["http://site:8000/ok"],
                   alarm_actions=["http://site:8000/alarm"],
                   insufficient_data_actions=["http://site:8000/nodata"],
                   matching_metadata={"project_id":
                                      "c96c887c216949acbdfbd8b494863567"}
                   )


class AlarmsController(rest.RestController):
    """Works on alarms."""

    def _get_user_context(self):
        """Get the context of the request
        """

        user = pecan.request.headers.get('X-User-Id', None)
        project = pecan.request.headers.get('X-Project-Id', None)
        is_admin = policy.check_is_admin([pecan.request.headers.get('X-Role')])
        auth_token = pecan.request.headers.get('X-Auth-Token')

        return context.RequestContext(auth_token=auth_token, user=user,
                                      tenant=project, is_admin=is_admin)

    def _input_sanitize(self, data):
        """Check and fix the definition of the alarm
        """
        # some fields are forbiden
        for k in ["id", "timestamp", "state_timestamp", "user_id",
                  "project_id"]:
            if getattr(data, k) is not wsme.Unset:
                raise wsme.exc.ClientSideError(_("%k should not be provided"))

        data.timestamp = timeutils.utcnow()
        LOG.debug("HEADERS %s", dict(pecan.request.headers))

        #FIXME(sileht): project_id can be not exists ?
        data.user_id = pecan.request.headers.get('X-User-Id', None)
        data.project_id = pecan.request.headers.get('X-Project-Id', None)

        if not policy.check_is_admin([pecan.request.headers.get('X-Role')]):
            data.matching_metadata['project_id'] = data.project_id

    @wsme_pecan.wsexpose(None, body=Alarm)
    def post(self, data):
        """Update a alarm

        :param id: id of the alarm
        :param data: definition of the alarm
        """

        self._input_sanitize(data)
        kwargs = data.as_dict(AlarmModel)
        try:
            alarm = AlarmModel(**kwargs)
        except:
            raise wsme.exc.ClientSideError(_("Alarm incorrect"))
        alarm = pecan.request.alarm_storage_conn.alarm_add(alarm)
        msg = {
            'method': 'add_or_update_alarm',
            'version': '1.0',
            'args': {'data': alarm.as_dict()},
        }
        rpc.cast(self._get_user_context(), cfg.CONF.alarms_topic, msg)

    @wsme_pecan.wsexpose(None, int, body=Alarm)
    def put(self, id, data):
        """Add a alarm

        :param id: id of the alarm
        :param data: definition of the alarm
        """
        self._input_sanitize(data)
        kwargs = data.as_dict(AlarmModel)

        try:
            alarm = pecan.request.alarm_storage_conn.alarm_get(id)
        except exception.AlarmNotFound:
            raise wsme.exc.ClientSideError(_("Unknown alarm"))

        for k, v in kwargs.iteritems():
            if k == 'state':
                alarm.state_timestamp = timeutils.utcnow()
            setattr(alarm, k, v)

        pecan.request.alarm_storage_conn.alarm_update(alarm)
        msg = {
            'method': 'add_or_update_alarm',
            'version': '1.0',
            'args': {'data': alarm.as_dict()},
        }
        rpc.cast(self._get_user_context(), cfg.CONF.alarms_topic, msg)

    @wsme_pecan.wsexpose(None, int, status_code=204)
    def delete(self, id):
        """Delete a alarm

        :param id: id of the alarm
        """
        try:
            pecan.request.alarm_storage_conn.alarm_delete(id)
        except exception.AlarmNotFound:
            raise wsme.exc.ClientSideError(_("Unknown alarm"))
        msg = {
            'method': 'delete_alarm',
            'version': '1.0',
            'args': {'id': id},
        }
        rpc.cast(self._get_user_context(), cfg.CONF.alarms_topic, msg)

    @wsme_pecan.wsexpose(Alarm, int)
    def get_one(self, id):
        """Return a alarm

        :param id: id of the alarm
        """

        try:
            alarm = pecan.request.alarm_storage_conn.alarm_get(id)
        except exception.AlarmNotFound:
            raise wsme.exc.ClientSideError(_("Unknown alarm"))

        alarm = Alarm.from_db_model(alarm)
        return alarm

    @wsme_pecan.wsexpose([Alarm], [Query])
    def get_all(self, q=[]):
        """Return all known alarms

        :param q: Filter rules for the alarms to be returned.
        """
        #FIXME(sileht): not sure its useful to use _query_to_kwargs
        kwargs = _query_to_kwargs(q,
                                  pecan.request.alarm_storage_conn.alarm_list)
        return [Alarm.from_db_model(
            pecan.request.alarm_storage_conn.alarm_get(m))
            for m in pecan.request.alarm_storage_conn.alarm_list(**kwargs)]


class V2Controller(object):
    """Version 2 API controller root."""

    resources = ResourcesController()
    meters = MetersController()
    alarms = AlarmsController()
