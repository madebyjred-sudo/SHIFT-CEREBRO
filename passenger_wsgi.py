"""
Ultra-minimal WSGI app — no imports, no dependencies.
If this works, Passenger is functional and the issue is in main.py imports.
"""
import sys

def application(environ, start_response):
    path = environ.get('PATH_INFO', '/')
    output = f"Passenger is alive!\n\nPython: {sys.version}\nPath: {path}\nApp root: {environ.get('DOCUMENT_ROOT', 'unknown')}"
    
    status = '200 OK'
    headers = [('Content-Type', 'text/plain'), ('Content-Length', str(len(output)))]
    start_response(status, headers)
    return [output.encode('utf-8')]
