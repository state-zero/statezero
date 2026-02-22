# =============================================================================
# StateZero Python Client Runtime
# This file is copied verbatim into generated packages as _runtime.py.
# No Django or statezero imports — only stdlib + httpx at runtime.
# =============================================================================

_transport = None
_upload_mode = "server"  # "server" or "s3"


# ---------------------------------------------------------------------------
# Error classes — match the backend's exception_handler.py response format
# ---------------------------------------------------------------------------

class StateZeroError(Exception):
    status_code = 500

    def __init__(self, detail=None):
        self.detail = detail or "A server error occurred."
        super().__init__(str(self.detail))


class ValidationError(StateZeroError):
    status_code = 400


class NotFound(StateZeroError):
    status_code = 404


class PermissionDenied(StateZeroError):
    status_code = 403


class MultipleObjectsReturned(StateZeroError):
    status_code = 400


class ConflictError(StateZeroError):
    status_code = 409


_ERROR_MAP = {
    "ValidationError": ValidationError,
    "NotFound": NotFound,
    "PermissionDenied": PermissionDenied,
    "MultipleObjectsReturned": MultipleObjectsReturned,
    "ConflictError": ConflictError,
}


def _parse_error(resp):
    """Parse error response and raise the appropriate exception."""
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        return
    error_type = data.get("type", "")
    detail = data.get("detail", str(data))
    exc_cls = _ERROR_MAP.get(error_type, StateZeroError)
    raise exc_cls(detail)


def configure(url=None, token=None, headers=None, transport=None, upload_mode="server"):
    """
    Configure the global transport for all model queries.

    Args:
        url: Base URL of the StateZero API (e.g. "https://api.example.com")
        token: Optional auth token (sent as "Token <token>")
        headers: Optional dict of extra headers
        transport: Optional custom transport object (must implement .post(model_name, body))
        upload_mode: "server" (direct upload) or "s3" (presigned URL upload). Default "server".
    """
    global _transport, _upload_mode
    if upload_mode not in ("server", "s3"):
        raise ValueError(f"upload_mode must be 'server' or 's3', got {upload_mode!r}")
    _upload_mode = upload_mode
    if transport:
        _transport = transport
    else:
        if not url:
            raise ValueError("Either url or transport must be provided")
        _transport = _HTTPTransport(url=url, token=token, headers=headers)


class _HTTPTransport:
    def __init__(self, url, token=None, headers=None):
        self.base_url = url.rstrip("/")
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        if token:
            self.headers["Authorization"] = f"Token {token}"

    def post(self, model_name, body):
        import httpx
        url = f"{self.base_url}/statezero/{model_name}/"
        resp = httpx.post(url, json=body, headers=self.headers, timeout=30.0)
        if resp.status_code >= 400:
            _parse_error(resp)
        return resp.json()

    def post_action(self, action_name, data):
        import httpx
        url = f"{self.base_url}/statezero/actions/{action_name}/"
        resp = httpx.post(url, json=data, headers=self.headers, timeout=30.0)
        if resp.status_code >= 400:
            _parse_error(resp)
        return resp.json()

    def validate(self, model_name, data, validate_type="create", partial=False):
        import httpx
        url = f"{self.base_url}/statezero/{model_name}/validate/"
        body = {"data": data, "validate_type": validate_type, "partial": partial}
        resp = httpx.post(url, json=body, headers=self.headers, timeout=30.0)
        if resp.status_code >= 400:
            _parse_error(resp)
        return resp.json()

    def get_field_permissions(self, model_name):
        import httpx
        url = f"{self.base_url}/statezero/{model_name}/field-permissions/"
        resp = httpx.get(url, headers=self.headers, timeout=30.0)
        if resp.status_code >= 400:
            _parse_error(resp)
        return resp.json()

    def upload_file(self, file_data, filename, content_type):
        """Direct upload via the server."""
        import httpx
        url = f"{self.base_url}/statezero/files/upload/"
        headers = {k: v for k, v in self.headers.items() if k.lower() != 'content-type'}
        files = {"file": (filename, file_data, content_type)}
        resp = httpx.post(url, files=files, headers=headers, timeout=120.0)
        resp.raise_for_status()
        return resp.json()

    def upload_file_s3(self, file_data, filename, content_type):
        """Upload via S3 presigned URLs (fast upload)."""
        import httpx
        import math

        chunk_size = 5 * 1024 * 1024  # 5 MB
        file_size = len(file_data)
        num_chunks = max(1, math.ceil(file_size / chunk_size))

        # Step 1: Initiate — get presigned URLs
        initiate_url = f"{self.base_url}/statezero/files/fast-upload/"
        init_resp = httpx.post(
            initiate_url,
            json={
                "action": "initiate",
                "filename": filename,
                "content_type": content_type,
                "file_size": file_size,
                "num_chunks": num_chunks,
            },
            headers=self.headers,
            timeout=30.0,
        )
        init_resp.raise_for_status()
        init_data = init_resp.json()
        file_path = init_data["file_path"]

        # Step 2: Upload data to S3
        if init_data["upload_type"] == "single":
            put_resp = httpx.put(
                init_data["upload_url"],
                content=file_data,
                headers={"Content-Type": content_type},
                timeout=120.0,
            )
            put_resp.raise_for_status()
            parts = []
        else:
            # Multipart
            upload_urls = init_data["upload_urls"]
            parts = []
            for part_num in range(1, num_chunks + 1):
                start = (part_num - 1) * chunk_size
                end = min(start + chunk_size, file_size)
                chunk = file_data[start:end]
                put_resp = httpx.put(
                    upload_urls[str(part_num)],
                    content=chunk,
                    headers={"Content-Type": content_type},
                    timeout=120.0,
                )
                put_resp.raise_for_status()
                etag = put_resp.headers.get("ETag", "").strip('"')
                parts.append({"PartNumber": part_num, "ETag": etag})

        # Step 3: Complete
        complete_resp = httpx.post(
            initiate_url,
            json={
                "action": "complete",
                "file_path": file_path,
                "original_name": filename,
                "upload_id": init_data.get("upload_id"),
                "parts": parts,
            },
            headers=self.headers,
            timeout=30.0,
        )
        complete_resp.raise_for_status()
        return complete_resp.json()


# ---------------------------------------------------------------------------
# FileObject — wraps files for upload
# ---------------------------------------------------------------------------

class FileObject:
    """Wraps a file for upload to the StateZero backend.

    Usage:
        # From file path
        f = FileObject("/path/to/report.pdf")

        # From bytes
        f = FileObject(b"content", name="data.txt")

        # From file-like object
        f = FileObject(open("report.pdf", "rb"))

        # From stored file data (API response)
        f = FileObject.from_stored({"file_path": "...", "file_url": "...", ...})

        # In create/update — client uploads automatically
        FileTest.objects.create(title="Report", document=f)
    """

    def __init__(self, source, name=None, content_type=None):
        import mimetypes
        from pathlib import Path

        if isinstance(source, (str, Path)):
            p = Path(source)
            self._name = name or p.name
            self._data = None
            self._path = p
        elif isinstance(source, bytes):
            if not name:
                raise ValueError("name is required when source is bytes")
            self._name = name
            self._data = source
            self._path = None
        elif hasattr(source, 'read'):
            self._name = name or getattr(source, 'name', None) or 'unnamed'
            self._data = source.read()
            if isinstance(self._data, str):
                self._data = self._data.encode('utf-8')
            self._path = None
        else:
            raise TypeError(f"Expected file path, bytes, or file-like object, got {type(source)}")

        self._content_type = content_type or mimetypes.guess_type(self._name)[0] or 'application/octet-stream'
        self._uploaded = False
        self._file_path = None
        self._upload_result = None

    @classmethod
    def from_stored(cls, data):
        """Create from stored file data returned by the API."""
        obj = object.__new__(cls)
        obj._name = data.get('original_name', '')
        obj._data = None
        obj._path = None
        obj._content_type = data.get('content_type', 'application/octet-stream')
        obj._uploaded = True
        obj._file_path = data['file_path']
        obj._upload_result = data
        return obj

    @property
    def file_path(self):
        return self._file_path

    @property
    def file_url(self):
        return self._upload_result.get('file_url') if self._upload_result else None

    @property
    def name(self):
        return self._name

    @property
    def uploaded(self):
        return self._uploaded

    def _get_data(self):
        if self._data is not None:
            return self._data
        if self._path:
            return self._path.read_bytes()
        raise ValueError("No file data available")

    def _upload(self, transport):
        """Upload via transport. Returns the file_path string."""
        if self._uploaded:
            return self._file_path
        data = self._get_data()
        if _upload_mode == "s3":
            result = transport.upload_file_s3(data, self._name, self._content_type)
        else:
            result = transport.upload_file(data, self._name, self._content_type)
        self._file_path = result['file_path']
        self._upload_result = result
        self._uploaded = True
        return self._file_path

    def __repr__(self):
        status = "uploaded" if self._uploaded else "pending"
        return f"FileObject({self._name!r}, {status})"


# ---------------------------------------------------------------------------
# Response cache — per-fetch, shared by all instances in that response
# ---------------------------------------------------------------------------

class _ResponseCache:
    def __init__(self, included):
        self._included = included  # {"model_name": {pk_str: {field_dict}}}

    def resolve(self, model_name, pk):
        model_data = self._included.get(model_name, {})
        # PKs in included are stringified — try both raw and str
        data = model_data.get(pk) or model_data.get(str(pk))
        if data is None:
            return pk  # not fetched, return raw PK
        model_cls = _model_registry.get(model_name)
        if model_cls:
            return model_cls._from_data(data, self)
        return data


# ---------------------------------------------------------------------------
# Model base class
# ---------------------------------------------------------------------------

_model_registry = {}  # model_name -> Model subclass


class Model:
    _model_name = ""
    _relations = {}     # {field_name: related_model_name}
    _pk_field = "id"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls._model_name:
            cls.objects = Manager(cls._model_name)
            _model_registry[cls._model_name] = cls

    @classmethod
    def _from_data(cls, data, cache):
        inst = object.__new__(cls)
        object.__setattr__(inst, '_raw', data)
        object.__setattr__(inst, '_cache', cache)
        return inst

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        raw = object.__getattribute__(self, '_raw')
        if name in type(self)._relations:
            fk = raw.get(name)
            if fk is None:
                return None
            cache = object.__getattribute__(self, '_cache')
            if cache:
                return cache.resolve(type(self)._relations[name], fk)
            return fk
        if name in raw:
            return raw[name]
        raise AttributeError(f"'{type(self).__name__}' has no field '{name}'")

    @property
    def pk(self):
        return self._raw.get(self._pk_field)

    def update(self, **data):
        return type(self).objects._queryset().update_instance(pk=self.pk, **data)

    def delete(self):
        return type(self).objects._queryset().delete_instance(pk=self.pk)

    def __repr__(self):
        repr_data = self._raw.get("repr", {})
        return repr_data.get("str", f"{type(self).__name__}(pk={self.pk})")

    def save(self):
        data = {k: v for k, v in self._raw.items() if k != self._pk_field and k != "repr"}
        if self.pk is not None:
            return self.update(**data)
        else:
            return type(self).objects.create(**data)

    def refresh_from_db(self):
        fresh = type(self).objects.get(**{self._pk_field: self.pk})
        object.__setattr__(self, '_raw', fresh._raw)
        object.__setattr__(self, '_cache', fresh._cache)
        return self

    def validate(self, validate_type="update", partial=False):
        data = {k: v for k, v in self._raw.items() if k != "repr"}
        return _transport.validate(self._model_name, data, validate_type, partial)

    @classmethod
    def validate_data(cls, data, validate_type="create", partial=False):
        return _transport.validate(cls._model_name, data, validate_type, partial)

    @classmethod
    def get_field_permissions(cls):
        if cls._model_name not in _field_permissions_cache:
            _field_permissions_cache[cls._model_name] = _transport.get_field_permissions(cls._model_name)
        return _field_permissions_cache[cls._model_name]

    def to_dict(self):
        return dict(self._raw)


_field_permissions_cache = {}


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class Manager:
    def __init__(self, model_name):
        self._model_name = model_name

    def _queryset(self):
        return QuerySet(self._model_name)

    def all(self):                          return self._queryset()
    def filter(self, *a, **kw):             return self._queryset().filter(*a, **kw)
    def exclude(self, *a, **kw):            return self._queryset().exclude(*a, **kw)
    def order_by(self, *f):                 return self._queryset().order_by(*f)
    def search(self, q, f=None):            return self._queryset().search(q, f)
    def get(self, **kw):                    return self._queryset().get(**kw)
    def first(self, **kw):                  return self._queryset().first(**kw)
    def last(self, **kw):                   return self._queryset().last(**kw)
    def count(self, **kw):                  return self._queryset().count(**kw)
    def exists(self):                       return self._queryset().exists()
    def create(self, **kw):                 return self._queryset().create(**kw)
    def bulk_create(self, data):            return self._queryset().bulk_create(data)
    def update(self, **kw):                 return self._queryset().update(**kw)
    def delete(self):                       return self._queryset().delete()
    def get_or_create(self, **kw):          return self._queryset().get_or_create(**kw)
    def update_or_create(self, **kw):       return self._queryset().update_or_create(**kw)
    def update_instance(self, **kw):        return self._queryset().update_instance(**kw)
    def delete_instance(self, **kw):        return self._queryset().delete_instance(**kw)
    def sum(self, field):                   return self._queryset().sum(field)
    def avg(self, field):                   return self._queryset().avg(field)
    def min(self, field):                   return self._queryset().min(field)
    def max(self, field):                   return self._queryset().max(field)


# ---------------------------------------------------------------------------
# Q — composable filter expressions
# ---------------------------------------------------------------------------

class Q:
    def __init__(self, connector="AND", **conditions):
        self._connector = connector.upper()
        self._conditions = conditions

    def _to_ast(self):
        if self._connector == "AND":
            return {"type": "filter", "conditions": self._conditions}
        else:
            children = [{"type": "filter", "conditions": {k: v}} for k, v in self._conditions.items()]
            return {"type": "or", "children": children}

    def __or__(self, other):
        return _CompoundQ("or", [self, other])

    def __and__(self, other):
        return _CompoundQ("and", [self, other])


class _CompoundQ:
    def __init__(self, connector, children):
        self._connector = connector
        self._children = children

    def _to_ast(self):
        return {"type": self._connector, "children": [c._to_ast() for c in self._children]}

    def __or__(self, other):
        return _CompoundQ("or", [self, other])

    def __and__(self, other):
        return _CompoundQ("and", [self, other])


# ---------------------------------------------------------------------------
# F — field references for computed updates (math.js AST)
# ---------------------------------------------------------------------------

class F:
    def __init__(self, field_name):
        self._node = {"mathjs": "SymbolNode", "name": field_name}

    @staticmethod
    def _wrap(val):
        if isinstance(val, F):
            return val._node
        return {"mathjs": "ConstantNode", "value": val}

    def _op(self, op, other):
        result = F.__new__(F)
        result._node = {"mathjs": "OperatorNode", "op": op, "args": [self._node, F._wrap(other)]}
        return result

    def _rop(self, op, other):
        result = F.__new__(F)
        result._node = {"mathjs": "OperatorNode", "op": op, "args": [F._wrap(other), self._node]}
        return result

    def __add__(self, o):       return self._op("+", o)
    def __radd__(self, o):      return self._rop("+", o)
    def __sub__(self, o):       return self._op("-", o)
    def __rsub__(self, o):      return self._rop("-", o)
    def __mul__(self, o):       return self._op("*", o)
    def __rmul__(self, o):      return self._rop("*", o)
    def __truediv__(self, o):   return self._op("/", o)
    def __rtruediv__(self, o):  return self._rop("/", o)
    def __mod__(self, o):       return self._op("%", o)
    def __pow__(self, o):       return self._op("^", o)

    def to_expr(self):
        return {"__f_expr": True, "ast": self._node}

    @staticmethod
    def _func(name, expr):
        result = F.__new__(F)
        result._node = {"mathjs": "FunctionNode",
                        "fn": {"mathjs": "SymbolNode", "name": name},
                        "args": [F._wrap(expr)]}
        return result

    @staticmethod
    def _func_n(name, args):
        result = F.__new__(F)
        result._node = {"mathjs": "FunctionNode",
                        "fn": {"mathjs": "SymbolNode", "name": name},
                        "args": [F._wrap(a) for a in args]}
        return result

    @staticmethod
    def abs(expr):
        return F._func("abs", expr)

    @staticmethod
    def round(expr, decimals=0):
        result = F.__new__(F)
        result._node = {"mathjs": "FunctionNode",
                        "fn": {"mathjs": "SymbolNode", "name": "round"},
                        "args": [F._wrap(expr), F._wrap(decimals)]}
        return result

    @staticmethod
    def floor(expr):
        return F._func("floor", expr)

    @staticmethod
    def ceil(expr):
        return F._func("ceil", expr)

    @staticmethod
    def min(*args):
        return F._func_n("min", args)

    @staticmethod
    def max(*args):
        return F._func_n("max", args)


# ---------------------------------------------------------------------------
# Data resolution — module-level so actions can import it directly
# ---------------------------------------------------------------------------

def _resolve_value(v):
    """Resolve non-JSON-serializable types before sending to the API."""
    from datetime import datetime, date
    from decimal import Decimal

    if isinstance(v, F):
        return v.to_expr()
    if isinstance(v, FileObject):
        return v._upload(_transport)
    if isinstance(v, Model):
        return v.pk
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, dict):
        return {dk: _resolve_value(dv) for dk, dv in v.items()}
    if isinstance(v, (list, tuple)):
        return [_resolve_value(item) for item in v]
    return v


# ---------------------------------------------------------------------------
# QuerySet — immutable, cloned on each chain method
# ---------------------------------------------------------------------------

class QuerySet:
    def __init__(self, model_name):
        self._model_name = model_name
        self._nodes = []       # list of ("filter"|"exclude", Q_or_CompoundQ)
        self._order_by = []
        self._search = None

    def _clone(self):
        qs = QuerySet(self._model_name)
        qs._nodes = list(self._nodes)
        qs._order_by = list(self._order_by)
        qs._search = self._search
        return qs

    # -- Chaining methods --

    def filter(self, *args, **kwargs):
        qs = self._clone()
        for arg in args:
            qs._nodes.append(("filter", arg))  # Q or _CompoundQ
        if kwargs:
            qs._nodes.append(("filter", Q(**kwargs)))
        return qs

    def exclude(self, *args, **kwargs):
        qs = self._clone()
        for arg in args:
            qs._nodes.append(("exclude", arg))
        if kwargs:
            qs._nodes.append(("exclude", Q(**kwargs)))
        return qs

    def all(self):
        return self._clone()

    def order_by(self, *fields):
        qs = self._clone()
        qs._order_by = list(fields)
        return qs

    def search(self, query, fields=None):
        qs = self._clone()
        qs._search = {"searchQuery": query}
        if fields:
            qs._search["searchFields"] = fields
        return qs

    def __iter__(self):
        return iter(self.fetch())

    def __len__(self):
        return self.count()

    # -- Query building (matches JS querySet.build()) --

    def _build(self):
        """Build the base query dict.

        Combines all filter/exclude nodes into a single 'filter' key,
        matching the JS client's querySet.build() output.
        """
        non_search = []
        for kind, q in self._nodes:
            node = q._to_ast() if hasattr(q, '_to_ast') else q
            if kind == "exclude":
                non_search.append({"type": "exclude", "child": node})
            else:
                non_search.append(node)

        if len(non_search) == 0:
            filter_node = None
        elif len(non_search) == 1:
            filter_node = non_search[0]
        else:
            filter_node = {"type": "and", "children": non_search}

        query = {}
        if filter_node is not None:
            query["filter"] = filter_node
        if self._search:
            query["search"] = self._search
        if self._order_by:
            query["orderBy"] = self._order_by
        return query

    # -- Transport --

    def _execute(self, query):
        """Send query to transport.

        Separates serializerOptions from the query and places it as a
        sibling of 'query' under 'ast', matching makeApiCall.js.
        """
        if _transport is None:
            raise RuntimeError("Client not configured. Call configure() first.")
        serializer_options = query.pop("serializerOptions", None)
        body = {"ast": {"query": query}}
        if serializer_options:
            body["ast"]["serializerOptions"] = serializer_options
        return _transport.post(self._model_name, body)

    # -- Response unwrapping --

    def _unwrap_list(self, response):
        serialized = response["data"]
        pks = serialized.get("data", [])
        included = serialized.get("included", {})
        model_name = serialized.get("model_name", self._model_name)
        cache = _ResponseCache(included)
        model_cls = _model_registry.get(model_name, Model)
        model_data = included.get(model_name, {})
        results = []
        for pk in pks:
            row = model_data.get(pk) or model_data.get(str(pk))
            if row:
                results.append(model_cls._from_data(row, cache))
        return results

    def _unwrap_instance(self, response):
        serialized = response["data"]
        pks = serialized.get("data", [])
        if not pks:
            return None
        included = serialized.get("included", {})
        model_name = serialized.get("model_name", self._model_name)
        cache = _ResponseCache(included)
        model_cls = _model_registry.get(model_name, Model)
        model_data = included.get(model_name, {})
        pk = pks[0]
        row = model_data.get(pk) or model_data.get(str(pk))
        if row:
            return model_cls._from_data(row, cache)
        return None

    # -- Data resolution --

    def _resolve_data(self, data):
        """Resolve non-JSON-serializable types in write data before sending."""
        return {k: _resolve_value(v) for k, v in data.items()}

    # -- Terminal methods --

    def fetch(self, limit=None, offset=None, depth=None, fields=None):
        query = {**self._build(), "type": "read"}
        serializer_options = {}
        if limit is not None:
            serializer_options["limit"] = limit
        if offset is not None:
            serializer_options["offset"] = offset
        if depth is not None:
            serializer_options["depth"] = depth
        if fields is not None:
            serializer_options["fields"] = fields
        if serializer_options:
            query["serializerOptions"] = serializer_options
        return self._unwrap_list(self._execute(query))

    def get(self, depth=None, fields=None, **conditions):
        qs = self.filter(**conditions) if conditions else self
        query = {**qs._build(), "type": "get"}
        serializer_options = {}
        if depth is not None:
            serializer_options["depth"] = depth
        if fields is not None:
            serializer_options["fields"] = fields
        if serializer_options:
            query["serializerOptions"] = serializer_options
        return self._unwrap_instance(self._execute(query))

    def first(self, depth=None, fields=None):
        query = {**self._build(), "type": "first"}
        serializer_options = {}
        if depth is not None:
            serializer_options["depth"] = depth
        if fields is not None:
            serializer_options["fields"] = fields
        if serializer_options:
            query["serializerOptions"] = serializer_options
        return self._unwrap_instance(self._execute(query))

    def last(self, depth=None, fields=None):
        query = {**self._build(), "type": "last"}
        serializer_options = {}
        if depth is not None:
            serializer_options["depth"] = depth
        if fields is not None:
            serializer_options["fields"] = fields
        if serializer_options:
            query["serializerOptions"] = serializer_options
        return self._unwrap_instance(self._execute(query))

    def exists(self):
        query = {**self._build(), "type": "exists"}
        return self._execute(query)["data"]

    def count(self, field="*"):
        query = {**self._build(), "type": "count", "field": field}
        return self._execute(query)["data"]

    def sum(self, field):
        query = {**self._build(), "type": "sum", "field": field}
        return self._execute(query)["data"]

    def avg(self, field):
        query = {**self._build(), "type": "avg", "field": field}
        return self._execute(query)["data"]

    def min(self, field):
        query = {**self._build(), "type": "min", "field": field}
        return self._execute(query)["data"]

    def max(self, field):
        query = {**self._build(), "type": "max", "field": field}
        return self._execute(query)["data"]

    def create(self, **data):
        resolved = self._resolve_data(data)
        query = {**self._build(), "type": "create", "data": resolved}
        return self._unwrap_instance(self._execute(query))

    def bulk_create(self, data):
        resolved = [self._resolve_data(item) for item in data]
        query = {**self._build(), "type": "bulk_create", "data": resolved}
        return self._unwrap_list(self._execute(query))

    def update(self, **data):
        resolved = self._resolve_data(data)
        query = {**self._build(), "type": "update", "data": resolved}
        return self._unwrap_list(self._execute(query))

    def delete(self):
        query = {**self._build(), "type": "delete"}
        return self._execute(query)["metadata"]["deleted_count"]

    def get_or_create(self, defaults=None, **lookup):
        query = {
            **self._build(),
            "type": "get_or_create",
            "lookup": lookup,
            "defaults": self._resolve_data(defaults) if defaults else {},
        }
        response = self._execute(query)
        instance = self._unwrap_instance(response)
        created = response.get("metadata", {}).get("created", False)
        return instance, created

    def update_or_create(self, defaults=None, **lookup):
        query = {
            **self._build(),
            "type": "update_or_create",
            "lookup": lookup,
            "defaults": self._resolve_data(defaults) if defaults else {},
        }
        response = self._execute(query)
        instance = self._unwrap_instance(response)
        created = response.get("metadata", {}).get("created", False)
        return instance, created

    def update_instance(self, pk=None, **data):
        resolved = self._resolve_data(data)
        pk_field = "id"
        model_cls = _model_registry.get(self._model_name)
        if model_cls:
            pk_field = model_cls._pk_field
        # Add PK as a filter node (server expects filter key for instance ops)
        qs = self.filter(**{pk_field: pk})
        query = {**qs._build(), "type": "update_instance", "data": resolved}
        return self._unwrap_instance(self._execute(query))

    def delete_instance(self, pk=None):
        pk_field = "id"
        model_cls = _model_registry.get(self._model_name)
        if model_cls:
            pk_field = model_cls._pk_field
        qs = self.filter(**{pk_field: pk})
        query = {**qs._build(), "type": "delete_instance"}
        return self._execute(query)["data"]
