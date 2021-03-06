# Copyright 2015 DataStax, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections import namedtuple
import logging
import six

from cassandra import ConsistencyLevel
from cassandra.cluster import Cluster, _NOT_SET, NoHostAvailable, UserTypeDoesNotExist
from cassandra.query import SimpleStatement, Statement, dict_factory

from cassandra.cqlengine import CQLEngineException
from cassandra.cqlengine.statements import BaseCQLStatement


log = logging.getLogger(__name__)

NOT_SET = _NOT_SET  # required for passing timeout to Session.execute

Host = namedtuple('Host', ['name', 'port'])

cluster = None
session = None
lazy_connect_args = None
default_consistency_level = ConsistencyLevel.ONE


# Because type models may be registered before a connection is present,
# and because sessions may be replaced, we must register UDTs here, in order
# to have them registered when a new session is established.
udt_by_keyspace = {}


class UndefinedKeyspaceException(CQLEngineException):
    pass


def default():
    """
    Configures the global mapper connection to localhost, using the driver defaults
    (except for row_factory)
    """
    global cluster, session

    if session:
        log.warning("configuring new connection for cqlengine when one was already set")

    cluster = Cluster()
    session = cluster.connect()
    session.row_factory = dict_factory

    _register_known_types(cluster)

    log.debug("cqlengine connection initialized with default session to localhost")


def set_session(s):
    """
    Configures the global mapper connection with a preexisting :class:`cassandra.cluster.Session`

    Note: the mapper presently requires a Session :attr:`~.row_factory` set to ``dict_factory``.
    This may be relaxed in the future
    """
    global cluster, session

    if session:
        log.warning("configuring new connection for cqlengine when one was already set")

    if s.row_factory is not dict_factory:
        raise CQLEngineException("Failed to initialize: 'Session.row_factory' must be 'dict_factory'.")
    session = s
    cluster = s.cluster

    _register_known_types(cluster)

    log.debug("cqlengine connection initialized with %s", s)


def setup(
        hosts,
        default_keyspace,
        consistency=ConsistencyLevel.ONE,
        lazy_connect=False,
        retry_connect=False,
        **kwargs):
    """
    Setup a the driver connection used by the mapper

    :param list hosts: list of hosts, (``contact_points`` for :class:`cassandra.cluster.Cluster`)
    :param str default_keyspace: The default keyspace to use
    :param int consistency: The global default :class:`~.ConsistencyLevel`
    :param bool lazy_connect: True if should not connect until first use
    :param bool retry_connect: True if we should retry to connect even if there was a connection failure initially
    :param \*\*kwargs: Pass-through keyword arguments for :class:`cassandra.cluster.Cluster`
    """
    global cluster, session, default_consistency_level, lazy_connect_args

    if 'username' in kwargs or 'password' in kwargs:
        raise CQLEngineException("username & password are now handled by using the native driver's auth_provider")

    from cassandra.cqlengine import models
    models.default_keyspace = default_keyspace

    default_consistency_level = consistency
    if lazy_connect:
        kwargs['default_keyspace'] = default_keyspace
        kwargs['consistency'] = consistency
        kwargs['lazy_connect'] = False
        kwargs['retry_connect'] = retry_connect
        lazy_connect_args = (hosts, kwargs)
        return

    cluster = cluster(hosts, **kwargs)
    try:
        session = cluster.connect()
        log.debug("cqlengine connection initialized with internally created session")
    except NoHostAvailable:
        if retry_connect:
            log.warning("connect failed, setting up for re-attempt on first use")
            kwargs['default_keyspace'] = default_keyspace
            kwargs['consistency'] = consistency
            kwargs['lazy_connect'] = False
            kwargs['retry_connect'] = retry_connect
            lazy_connect_args = (hosts, kwargs)
        raise
    session.row_factory = dict_factory

    _register_known_types(cluster)


def setup_connections(connections, **kwargs):
    """Replaces the global session variable with a SessionManager object
    and sets up the sessions for the connection parameters provided
    in the connections dict.

    Expected format of connections dict.

    CASSANDRA_CONNECTIONS = {
        <cluster_name_1:str>: {
            <keyspace:str>: <hosts:list>
         },
        <cluster_name_2:str>: {
            <keyspace: str>: <hosts:list>
        }
    }
    """
    global session
    session = SessionManager()
    for cluster_name, hosts_info in connections.iteritems():
        for keyspace, hosts in hosts_info.iteritems():
            session.add_connection(hosts, keyspace, cluster_name)


def execute(query, params=None, consistency_level=None, timeout=NOT_SET,
        connection_key=None):

    handle_lazy_connect()

    if not session:
        raise CQLEngineException("It is required to setup() cqlengine before executing queries")

    if consistency_level is None:
        consistency_level = default_consistency_level

    if isinstance(query, Statement):
        pass

    elif isinstance(query, BaseCQLStatement):
        params = query.get_context()
        query = str(query)
        query = SimpleStatement(query, consistency_level=consistency_level)

    elif isinstance(query, six.string_types):
        query = SimpleStatement(query, consistency_level=consistency_level)

    log.debug(query.query_string)

    params = params or {}
    result = session.execute(query, params, timeout=timeout,
            connection_key=connection_key)

    return result

class SessionManager(object):
    """SessionManager replaces the native Session object that is set globally.
    This class is responsible for maintaining multiple sessions per  cluster
    and keyspace combination.
    """
    def __init__(self):
        self._sessions = {}
        self._clusters = {}

    def create_cluster_and_session(self, cluster_name, hosts):
        cluster = Cluster(hosts)
        try:
            session = cluster.connect()
            log.debug("SessionManager: setting up connection ")
        except Exception, e:
            raise
        session.row_factory = dict_factory
        return (cluster, session)

    def add_connection(self, hosts, keyspace, cluster_name):
        (cluster, session) = self.create_cluster_and_session(cluster_name, hosts)
        key = get_connection_key(cluster_name, keyspace)
        self._sessions.update({
            key: session})
        self._clusters.update({
            key: cluster
            })

    def execute(self, query, parameters=None, timeout=NOT_SET, trace=False,
            connection_key=None):
       session = self._sessions.get(connection_key)
       if not session:
           raise Exception("No session found for the given session key" +
                   connection_key)
       return session.execute(query, parameters=parameters, timeout=timeout,
               trace=trace)


def get_session():
    handle_lazy_connect()
    return session

def get_connection_key(clustername, keyspace):
    """Returns the key for the given clustername and keyspace.

    This key is mapped to its  Session object in global object
    of SessionManager class.
    """
    key_format = "{clustername}__{keyspace}"
    key = key_format.format(clustername=clustername, keyspace=keyspace)
    return key

def get_cluster(clustername, keyspace):
    #handle_lazy_connect()
    global session
    connection_key = get_connection_key(clustername, keyspace)
    print connection_key
    print session._clusters
    cluster = session._clusters.get(connection_key)
    if not cluster:
        raise CQLEngineException("%s.cluster is not configured. Call one of the setup or default functions first." % __name__)
    return cluster


def handle_lazy_connect():
    global lazy_connect_args
    if lazy_connect_args:
        log.debug("lazy connect")
        hosts, kwargs = lazy_connect_args
        lazy_connect_args = None
        setup(hosts, **kwargs)


def register_udt(keyspace, type_name, klass):
    try:
        udt_by_keyspace[keyspace][type_name] = klass
    except KeyError:
        udt_by_keyspace[keyspace] = {type_name: klass}

    global cluster
    if cluster:
        try:
            cluster.register_user_type(keyspace, type_name, klass)
        except UserTypeDoesNotExist:
            pass  # new types are covered in management sync functions


def _register_known_types(cluster):
    for ks_name, name_type_map in udt_by_keyspace.items():
        for type_name, klass in name_type_map.items():
            try:
                cluster.register_user_type(ks_name, type_name, klass)
            except UserTypeDoesNotExist:
                pass  # new types are covered in management sync functions




