"""A proxy server between the Streamlit libs and web client.

Internally, the Proxy basically does bookkeeping for a set of ProxyConnection
objects. A ProxyConnection always has:

    - One "local" connection to the python libs.
    - Zero or more "client" connections to the web client.

Essentially, the ProxyConnection stays open so long as any of those connections
do. When the final ProxyConnection closes, then the whole proxy does tooself.

To ensure the proxy closes, a short timeout is launched for each connection
which closes the proxy if no connections were established.

Events
------

More concretely, we can think of the "life of a ProxyConnection" as subject
to five events, which we denote [LC-], [LC+], [CC-], [CC+], and [T]:

A ProxyConnection is considered "current" if it's the active connection for its
name.

    - [LC-] : The local connection is closed.
    - [LC+] : A new local connection is opened. This one is no longer current.
    - [CC-] : A client connection for this ProxyConnection is closed.
    - [CC+] : A client connection for this ProxyConnection is opened.
    - [T]   : The connection timeout arrives.

State Diagram Perspective
-------------------------

This state transition table lists what happens to a ProxyConnection when
various events come in, depending on the state.

    - State 1 (Current. No client connections yet.)
        - [LC-] : Do nothing.
        - [LC+] : Make this no longer current. Go to state 3.
        - [CC-] : Impossible.
        - [CC+] : Remember that has had client connection. Go to State 2.
        - [T]   : Remove this connection. Potentially close the proxy.

    - State 2 (Current. At least one open connection.)
        - [LC-] : If no client connections:
                    Remove this connection. Potentially close the proxy.
        - [LC+] : Make this no longer current. Go to state 4.
        - [CC-] : If no client connections AND no local connection:
                    Remove this connection. Potentially close the proxy.
        - [CC+] : Do nothing
        - [T]   : Do nothing

    - State 3 (No longer current. No client connections yet.)
        -> Note: We should try to close the local connection.
        - [LC-] : Potentially close the proxy.
        - [LC+] : Do nothing.
        - [CC-] : Impossible.
        - [CC+] : Impossible.
        - [T]   : Remove this connection. Potentially close the proxy.

    - State 4 (No longer current. Has received client connections.)
        -> Note: We should try to close the local connection.
        - [LC-] : Potentially close the proxy.
        - [LC+] : Do nothing.
        - [CC-] : Potentially close the proxy.
        - [CC+] : Impossible.
        - [T]   : Do nothing.

Imperative Perspective
----------------------

The state transition dialog above should be equivalent to the following
imperative description of the behavior of a ProxyConnection

    - [LC-] :
        if is_current and NOT received_connection:
            Do nothing. (Return early.)
        if received_connection AND NOT has_client_connections:
            Remove this connection.
        Potentially close the proxy.
    - [LC+] :
        Make this no longer current.
    - [CC-] :
        If no client connections and no local connection
            Remove this connection.
        Potentially close the proxy
    - [CC+] :
        Remember that has had client connection.
    - [T]   :
        If NOT received_connection:
            Remove this connection.
            Potentially close the proxy.

State for ProxyConnection
-------------------------
    - Name of the connection.
    - Has received client connection.
    - Master queue for the local connection.
    - One or mo

Tests
-----

- Start a long process. Then, start another with the same name. What happens to
  the first?
-
"""

from aiohttp import web, WSMsgType
import asyncio
import os
import urllib
import webbrowser

from streamlit.shared import config
from streamlit.shared.ReportQueue import ReportQueue
from streamlit.shared.streamlit_msg_proto import new_report_msg
from streamlit.shared.streamlit_msg_proto import streamlit_msg_iter

def _stop_proxy_on_exception(coroutine):
    """Coroutine decorator which stops the the proxy if an exception
    propagates out of the inner coroutine."""
    async def wrapped_coroutine(*args, **kwargs):
        try:
            return await coroutine(*args, **kwargs)
        except:
            asyncio.get_event_loop().stop()
            raise
    wrapped_coroutine.__name__ = coroutine.__name__
    wrapped_coroutine.__doc__ = coroutine.__doc__
    return wrapped_coroutine

class Proxy:
    """The main base class for the streamlit server."""

    def __init__(self):
        # Set up the server.
        self._app = web.Application()
        self._app.router.add_routes([
            # Local connection to stream a new report.
            web.get('/new/{local_id}/{report_name}', self._local_ws_handler),

            # Client connection (serves up index.html)
            web.get('/report/{report_name}', self._client_html_handler),

            # Outgoing endpoint to get the latest report.
            web.get('/stream/{report_name}', self._client_ws_handler)
        ])

        # If we're not using the node development server, then the proxy
        # will serve up the development pages.
        if not config.get_option('proxy.useNode'):
            static_path = config.get_path('proxy.staticRoot')
            self._app.router.add_static('/', path=static_path)

        # This table from names to ProxyConnections stores all the information
        # about our connections. When the number of connections drops to zero,
        # then the proxy shuts down.
        self._connections = {}

    def run_app(self):
        """Runs the web app."""
        port = config.get_option('proxy.port')
        web.run_app(self._app, port=port)
        print('Closing down the Streamlit proxy server.')

    # def _close_server_on_connection_timeout(self):
    #     """Closes the server if we haven't received a connection in a certain
    #     amount of time."""
    #     # Init the state for the timeout
    #     timeout_secs = config.get_option('proxy.waitForConnectionSecs')
    #     loop = asyncio.get_event_loop()
    #
    #     # Enqueue the timeout in the event loop.
    #     def close_server_if_necessary():
    #         if self._n_inbound_connections < 1:
    #             loop.stop()
    #     loop.call_later(timeout_secs, close_server_if_necessary)

    @_stop_proxy_on_exception
    async def _local_ws_handler(self, request):
        """Handles a connection to a "local" instance of Streamlit, i.e.
        one producing deltas to display on the client."""
        # Parse out the control information.
        local_id = request.match_info.get('local_id')
        report_name = request.match_info.get('report_name')
        report_name = urllib.parse.unquote_plus(report_name)

        print(f'Got a connection with UNQUOTED name="{report_name}".')

        # Establishe the websocket.
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Instantiate a new queue and stream data into it.
        connection = None
        async for msg in streamlit_msg_iter(ws):
            msg_type = msg.WhichOneof('type')
            if msg_type == 'new_report':
                report_id = msg.new_report
                connection = ProxyConnection(report_id, report_name)
                self._register(connection)
                print(f'Registered connection name="{report_name}" and id={report_id}')
            elif msg_type == 'delta_list':
                assert connection != None, \
                    'The protocol prohibits `delta_list` before `new_report`.'
                for delta in msg.delta_list.deltas:
                    connection.enqueue(delta)
            else:
                raise RuntimeError(f'Cannot parse message type: {msg_type}')

        # Deregister this connection and see if we can close the proxy.
        connection.finished_local_connection()
        if connection.has_had_clients() and not connection.has_clients():
            self._deregister(connection)
        self._potentially_stop_proxy()
        return ws

    @_stop_proxy_on_exception
    async def _client_html_handler(self, request):
        static_root = config.get_path('proxy.staticRoot')
        return web.FileResponse(os.path.join(static_root, 'index.html'))

    @_stop_proxy_on_exception
    async def _client_ws_handler(self, request):
        """This is what the web client connects to."""
        # How long we wait between sending more data.
        throttle_secs = config.get_option('local.throttleSecs')

        # Get the report name
        report_name = request.match_info.get('report_name')
        # raise RuntimeError(f'Got incoming websocket connection with name="{report_name}"')

        # Establishe the websocket.
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Stream the data across.
        connection, queue = await self._add_client(report_name, ws)
        while True:
            # See if the queue has changed.
            if connection != self._connections[report_name]:
                print('GOT A NEW CONNECTION')
                self._remove_client(connection, queue)
                connection, queue = await self._add_client(report_name, ws)

            # Send any new deltas across the wire.
            await queue.flush_deltas(ws)

            # Watch for a CLOSE method as we sleep for throttle_secs.
            try:
                msg = await ws.receive(timeout=throttle_secs)
                if msg.type != WSMsgType.CLOSE:
                    print('Unknown message type:', msg.type)
                break
            except asyncio.TimeoutError:
                pass
        print('Received the close message for "%s". Now removing the final queue.' % report_name)

        self._remove_client(connection, queue)
        return ws

    def _lauch_web_client(self, name):
        """Launches a web browser to connect to the proxy to get the named
        report.

        Args
        ----
        name : string
            The name of the report to which the web browser should connect.
        """
        if config.get_option('proxy.useNode'):
            host, port = 'localhost', '3000'
        else:
            host = config.get_option('proxy.server')
            port = config.get_option('proxy.port')
        url = f'http://{host}:{port}/report/{name}'
        webbrowser.open(url)

    def _register(self, connection):
        """Registers this connection under it's name so that client connections
        will connect to it."""
        new_name = connection.name not in self._connections
        self._connections[connection.name] = connection
        if new_name:
            self._lauch_web_client(connection.name)
        list(map(print, ['registered connections:'] + [('  - ' + c) for c in self._connections]))
        print('(%i connections)' % len(self._connections))

    def _deregister(self, connection):
        """Sever the association between this connection and it's name."""
        print(f'DEREGISTERING {connection.name} n_connections={len(self._connections)}.')
        if self._is_registered(connection):
            del self._connections[connection.name]
            print('Removed the connection with name "%s"' % connection.name)
        print(f'FINISHED DEREGISTERING {connection.name} n_connections={len(self._connections)}.')
        list(map(print, ['registered connections:'] + [('  - ' + c) for c in self._connections]))
        print('(%i connections)' % len(self._connections))

    def _is_registered(self, connection):
        """Returns true if this connection is registered to its name."""
        return self._connections[connection.name] is connection

    async def _add_client(self, report_name, ws):
        """Adds a queue to the connection for the given report_name."""
        connection = self._connections[report_name]
        queue = connection.add_client_queue()
        print('sending new report with id=', connection.id)
        await new_report_msg(connection.id, ws)
        return (connection, queue)

    def _remove_client(self, connection, queue):
        """Removes the queue from the connection, and closes the connection if
        necessary."""
        connection.remove_client_queue(queue)
        if not (connection.has_clients() or connection.has_local()):
            self._deregister(connection)
        self._potentially_stop_proxy()

    def _potentially_stop_proxy(self):
        """Checks to see if we have any open connections. If not,
        close the proxy."""
        print('TESTING to see if we can stop the proxy...')
        list(map(print, ['registered connections:'] + [('  - ' + c) for c in self._connections]))
        print('(%i connections)' % len(self._connections))
        if not self._connections:
            asyncio.get_event_loop().stop()
        # raise NotImplementedError('Need to implement _potentially_stop_proxy')
            #

class ProxyConnection:
    """Stores information shared by both local_connections and
    client_connections related to a particular report."""

    def __init__(self, id, name):
        # The unique BSON ID of this report.
        self.id = id

        # The name for this report.
        self.name = name

        # When the local connection ends, this flag becomes false.
        self._has_local = True

        # When we recieve a client connection, this flag becomes true.
        self._has_had_clients = False

        # A master queue for incoming deltas, replicated for each connection.
        self._master_queue = ReportQueue()

        # Each connection additionally gets its own queue.
        self._client_queues = []

    def finished_local_connection(self):
        """Removes the flag indicating an active local connection."""
        self._has_local = False

    def has_local(self):
        """Returns true if we have an active local connection."""
        return self._has_local

    def has_had_clients(self):
        """Returns true if this client has ever had a client connection."""
        return self._has_had_clients

    def has_clients(self):
        """Returns true if the connection currently has client connections."""
        return bool(self._client_queues)

    def enqueue(self, delta):
        """Stores the delta in the master queue and transmits to all clients
        via client_queues."""
        self._master_queue(delta)
        for queue in self._client_queues:
            queue(delta)

    def add_client_queue(self):
        """Adds a queue for a new client by cloning the master queue."""
        new_queue = self._master_queue.clone()
        self._client_queues.append(new_queue)
        self._has_had_clients = True
        return new_queue

    def remove_client_queue(self, queue):
        """Removes the client queue. Returns True iff the client queue list is
        empty."""
        print('BEFORE REMOVE', len(self._client_queues))
        self._client_queues.remove(queue)
        print('AFTER REMOVE', len(self._client_queues))

    # def has_clients(self):
    #     """Indicates that there are still clients connected here."""
    #     return len(self._client_queues) > 0

def main():
    """
    Creates a proxy server and launches the browser to connect to it.
    The proxy server will close when the browswer connection closes (or if
    it times out waiting for the browser connection.)
    """
    proxy_server = Proxy()
    proxy_server.run_app()

if __name__ == '__main__':
    main()
