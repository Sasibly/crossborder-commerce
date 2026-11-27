"""Probe loopback readiness while validating the configured certificate DNS name."""
import os
import socket
import ssl


def main():
    name=os.environ.get('COMMERCE_TLS_SERVER_NAME','localhost')
    if not name or any(c.isspace() or c in '/@' for c in name):raise ValueError('Invalid TLS server name')
    port=int(os.environ.get('COMMERCE_TLS_PORT','8000'))
    ca=os.environ.get('COMMERCE_TLS_TRUST_CA_FILE','/run/secrets/tls_trust_ca')
    context=ssl.create_default_context(cafile=ca)
    with socket.create_connection(('127.0.0.1',port),timeout=3) as raw:
        with context.wrap_socket(raw,server_hostname=name) as secure:
            secure.sendall(('GET /ready HTTP/1.1\r\nHost: '+name+'\r\nConnection: close\r\n\r\n').encode('ascii'))
            with secure.makefile('rb') as response:
                if response.readline().split()[1:2]!=[b'200']:raise RuntimeError('Application not ready over verified TLS')


if __name__=='__main__':main()
