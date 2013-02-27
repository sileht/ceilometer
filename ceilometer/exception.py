# -*- encoding: utf-8 -*-
#
# Copyright © 2013 eNovance <licensing@enovance.com>
#
# Author: Mehdi Abaakouk <mehdi.abaakouk@enovance.com>
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

_FATAL_EXCEPTION_FORMAT_ERRORS = False

from ceilometer.openstack.common.gettextutils import _


class CeilometerException(Exception):
    """
    Base Ceilometer Exception

    To correctly use this class, inherit from it and define
    a 'message' property. That message will get printf'd
    with the keyword arguments provided to the constructor.
    """
    message = _("An unknown exception occurred")

    def __init__(self, message=None, *args, **kwargs):
        if not message:
            message = self.message
        try:
            message = message % kwargs
        except Exception as e:
            if _FATAL_EXCEPTION_FORMAT_ERRORS:
                raise e
            else:
                # at least get the core message out if something happened
                pass

        super(CeilometerException, self).__init__(message)


class InvalidComparisonOperator(CeilometerException):
    message = _("The comparison operator '%(comparison_operator)s' of the \
                alarm '%(name)s' is invalid")


class AggregateNotFound(CeilometerException):
    message = _("The aggregate %(aggregate)s doesn't exists")


class AlarmNotFound(CeilometerException):
    message = _("The alarm %(alarm)s doesn't exists")
