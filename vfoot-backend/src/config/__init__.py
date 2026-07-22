"""Package init.

Django's MySQL backend expects the ``MySQLdb`` module (the C extension shipped by
``mysqlclient``), which needs system dev headers to build. Where those aren't
available, PyMySQL — pure Python, pip-installable anywhere — can stand in for it.
We register it only as a FALLBACK, so a machine with the real mysqlclient keeps
using it.
"""
try:  # pragma: no cover - import-time shim
    import MySQLdb  # noqa: F401  (the real thing, if present)
except ImportError:  # pragma: no cover
    try:
        import pymysql

        pymysql.install_as_MySQLdb()
    except ImportError:
        pass  # no MySQL driver at all: fine unless DB_ENGINE=mysql
