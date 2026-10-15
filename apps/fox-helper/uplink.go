package main

import (
	"net"
	"net/http"
	"time"
)

func (p *provider) relayDialer() *net.Dialer {
	d := &net.Dialer{Timeout: 10 * time.Second, KeepAlive: 30 * time.Second}
	d.Control = interfaceControl(p.bindInterface)
	return d
}

func (p *provider) bindUplink(name string) error {
	if name != "" {
		if _, err := net.InterfaceByName(name); err != nil {
			return err
		}
	}
	p.bindInterface = name
	p.client.Transport.(*http.Transport).DialContext = p.relayDialer().DialContext
	return nil
}
