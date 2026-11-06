package routing

import (
	"errors"
	"fmt"
	"net/netip"
	"os"
	"strings"
)

// The geo files are v2ray's protobuf lists (v2ray-core app/router config):
//
//	GeoSiteList { repeated GeoSite entry = 1; }
//	GeoSite     { string country_code = 1; repeated Domain domain = 2; }
//	Domain      { Type type = 1; string value = 2; ... }  // Plain, Regex, Domain, Full
//	GeoIPList   { repeated GeoIP entry = 1; }
//	GeoIP       { string country_code = 1; repeated CIDR cidr = 2; bool reverse_match = 3; }
//	CIDR        { bytes ip = 1; uint32 prefix = 2; }
//
// Only the wire format is needed, so it is read here without a protobuf
// library. Only the requested tags are decoded, which keeps loading a
// large file fast.

// v2ray Domain types.
const (
	domainPlain  = 0 // keyword: the value appears anywhere in the name
	domainRegex  = 1
	domainSuffix = 2 // the name or any name under it
	domainFull   = 3
)

var errTruncated = errors.New("truncated protobuf data")

// wire reads protobuf fields from a byte slice.
type wire struct{ b []byte }

func (w *wire) varint() (uint64, error) {
	var v uint64
	for shift := uint(0); shift < 64; shift += 7 {
		if len(w.b) == 0 {
			return 0, errTruncated
		}
		c := w.b[0]
		w.b = w.b[1:]
		v |= uint64(c&0x7f) << shift
		if c < 0x80 {
			return v, nil
		}
	}
	return 0, errors.New("varint overflow")
}

// next returns the next field number, wire type, and, for length-delimited
// fields, the bytes; varint values are returned in n.
func (w *wire) next() (field int, typ int, data []byte, n uint64, err error) {
	key, err := w.varint()
	if err != nil {
		return 0, 0, nil, 0, err
	}
	field, typ = int(key>>3), int(key&7)
	switch typ {
	case 0:
		n, err = w.varint()
	case 1:
		if len(w.b) < 8 {
			return 0, 0, nil, 0, errTruncated
		}
		w.b = w.b[8:]
	case 2:
		var size uint64
		if size, err = w.varint(); err == nil {
			if uint64(len(w.b)) < size {
				return 0, 0, nil, 0, errTruncated
			}
			data, w.b = w.b[:size], w.b[size:]
		}
	case 5:
		if len(w.b) < 4 {
			return 0, 0, nil, 0, errTruncated
		}
		w.b = w.b[4:]
	default:
		err = fmt.Errorf("unsupported protobuf wire type %d", typ)
	}
	return field, typ, data, n, err
}

// entries calls fn with the tag and body of every entry of a GeoSiteList
// or GeoIPList whose tag (lower case) is wanted.
func entries(data []byte, want func(tag string) bool, fn func(tag string, body []byte) error) error {
	list := wire{data}
	for len(list.b) > 0 {
		field, typ, entry, _, err := list.next()
		if err != nil {
			return err
		}
		if field != 1 || typ != 2 {
			continue
		}
		// The tag is the first field in practice; read it without decoding
		// the rest of an unwanted entry.
		e := wire{entry}
		tag := ""
		for len(e.b) > 0 {
			f, t, value, _, err := e.next()
			if err != nil {
				return err
			}
			if f == 1 && t == 2 {
				tag = strings.ToLower(string(value))
				break
			}
		}
		if want(tag) {
			if err := fn(tag, entry); err != nil {
				return fmt.Errorf("%s: %w", tag, err)
			}
		}
	}
	return nil
}

// Tags lists the tags of a geo file, for messages.
func Tags(path string) ([]string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var tags []string
	err = entries(data, func(string) bool { return true }, func(tag string, _ []byte) error {
		tags = append(tags, tag)
		return nil
	})
	return tags, err
}

// loadGeoSite reads the domains of the wanted tags of a geosite file into
// sets by tag.
func loadGeoSite(path string, wanted map[string]bool) (map[string]*DomainSet, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	sets := make(map[string]*DomainSet)
	err = entries(data, func(tag string) bool { return wanted[tag] }, func(tag string, body []byte) error {
		set := sets[tag]
		if set == nil {
			set = newDomainSet()
			sets[tag] = set
		}
		e := wire{body}
		for len(e.b) > 0 {
			field, typ, domain, _, err := e.next()
			if err != nil {
				return err
			}
			if field != 2 || typ != 2 {
				continue
			}
			kind, value, err := readDomain(domain)
			if err != nil {
				return err
			}
			if err := set.add(kind, value); err != nil {
				return err
			}
		}
		return nil
	})
	return sets, err
}

func readDomain(data []byte) (kind int, value string, err error) {
	d := wire{data}
	for len(d.b) > 0 {
		field, typ, bytes, n, err := d.next()
		if err != nil {
			return 0, "", err
		}
		switch {
		case field == 1 && typ == 0:
			kind = int(n)
		case field == 2 && typ == 2:
			value = string(bytes)
		}
	}
	return kind, value, nil
}

// loadGeoIP reads the networks of the wanted tags of a geoip file into
// sets by tag.
func loadGeoIP(path string, wanted map[string]bool) (map[string]*IPSet, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	sets := make(map[string]*IPSet)
	err = entries(data, func(tag string) bool { return wanted[tag] }, func(tag string, body []byte) error {
		set := sets[tag]
		if set == nil {
			set = &IPSet{}
			sets[tag] = set
		}
		e := wire{body}
		for len(e.b) > 0 {
			field, typ, cidr, n, err := e.next()
			if err != nil {
				return err
			}
			switch {
			case field == 2 && typ == 2:
				prefix, err := readCIDR(cidr)
				if err != nil {
					return err
				}
				set.add(prefix)
			case field == 3 && typ == 0 && n != 0:
				return errors.New("reverse_match lists are not supported")
			}
		}
		return nil
	})
	for _, set := range sets {
		set.finish()
	}
	return sets, err
}

func readCIDR(data []byte) (netip.Prefix, error) {
	var ip []byte
	var bits uint64
	c := wire{data}
	for len(c.b) > 0 {
		field, typ, value, n, err := c.next()
		if err != nil {
			return netip.Prefix{}, err
		}
		switch {
		case field == 1 && typ == 2:
			ip = value
		case field == 2 && typ == 0:
			bits = n
		}
	}
	addr, ok := netip.AddrFromSlice(ip)
	if !ok || int(bits) > addr.BitLen() {
		return netip.Prefix{}, fmt.Errorf("invalid CIDR %x/%d", ip, bits)
	}
	if addr.Is4In6() {
		if bits < 96 {
			return netip.Prefix{}, fmt.Errorf("invalid CIDR %x/%d", ip, bits)
		}
		addr, bits = addr.Unmap(), bits-96
	}
	return netip.PrefixFrom(addr, int(bits)).Masked(), nil
}
