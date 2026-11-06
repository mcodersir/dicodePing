package proxy

import "syscall"

// noNetworkErrnos are the socket errors that mean this computer has no
// route to the internet (Winsock: WSAENETDOWN, WSAENETUNREACH,
// WSAEHOSTUNREACH).
var noNetworkErrnos = []syscall.Errno{10050, 10051, 10065}

// cutErrnos are a connection refused, reset, or aborted (Winsock:
// WSAECONNABORTED, WSAECONNRESET, WSAECONNREFUSED, and Go's own numbers).
var cutErrnos = []syscall.Errno{10053, 10054, 10061, syscall.ECONNRESET, syscall.ECONNABORTED, syscall.ECONNREFUSED}
