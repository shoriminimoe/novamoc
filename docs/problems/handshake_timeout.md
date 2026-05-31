# Handshake timeout

The client opened the `/sync/live` WebSocket but did not send its `hello`
frame within the handshake window. The server closes idle un-handshaked
sockets to avoid leaking connections.

Send the `hello` frame immediately after the socket opens. The connection
is closed with WebSocket code `1008` (policy violation).
