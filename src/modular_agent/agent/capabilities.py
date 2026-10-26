"""File-backed public contracts. No imports, commands or credentials in manifests."""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import re


def validate_schema(value, schema, path='params', *, references=False):
    """Validate the documented JSON Schema subset; reject unknown arguments."""
    if references and isinstance(value, dict) and set(value) == {'$ref'}:
        if not isinstance(value['$ref'], str):
            raise ValueError(path + ': $ref must be a string')
        return deepcopy(value)
    kind = schema['type']
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'boolean': type(value) is bool,
             'integer': type(value) is int, 'number': type(value) in (int, float)}
    if kind not in valid or not valid[kind]:
        raise ValueError(f'{path}: expected {kind}')
    if kind in ('integer', 'number'):
        if not math.isfinite(value):
            raise ValueError(path + ': must be finite')
        if value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf):
            raise ValueError(path + ': outside permitted range')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(path + ': unsupported value')
    if kind == 'object':
        properties = schema.get('properties', {})
        unknown = value.keys() - properties.keys()
        if unknown and schema.get('additionalProperties', False) is False:
            raise ValueError(path + ': unknown fields ' + ', '.join(sorted(unknown)))
        missing = set(schema.get('required', [])) - value.keys()
        if missing:
            raise ValueError(path + ': missing ' + ', '.join(sorted(missing)))
        result = {}
        for key, child in properties.items():
            if key in value:
                result[key] = validate_schema(value[key], child, path + '.' + key, references=references)
            elif 'default' in child:
                result[key] = validate_schema(deepcopy(child['default']), child, path + '.' + key)
        return result
    if kind == 'array':
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 1000):
            raise ValueError(path + ': invalid item count')
        return [validate_schema(v, schema['items'], f'{path}[{i}]', references=references)
                for i, v in enumerate(value)]
    if kind == 'string':
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 4096):
            raise ValueError(path + ': invalid string length')
    return deepcopy(value)


class CapabilityCatalog:
    def __init__(self, root):
        self.root = Path(root)
        self.entries = {}
        for path in sorted((self.root / 'domains').glob('*/capabilities.json')):
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            if data.get('schema_version') != 1 or data.get('domain') != path.parent.name:
                raise ValueError('Invalid capability manifest: ' + str(path))
            for entry in data['capabilities']:
                name = entry['id']
                if not re.fullmatch(r'[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*', name) or name in self.entries:
                    raise ValueError('Invalid/duplicate capability: ' + name)
                if name.split('.')[0] != data['domain']:
                    raise ValueError('Capability domain mismatch: ' + name)
                self.entries[name] = {**entry, 'domain': data['domain'],
                                      'source': path.relative_to(self.root).as_posix()}

    def read(self, name):
        if name not in self.entries:
            raise ValueError('Unknown capability: ' + str(name))
        return deepcopy(self.entries[name])

    def index(self, domain=None):
        return [{k: deepcopy(e[k]) for k in ('id', 'domain', 'description', 'source', 'requires')}
                for e in self.entries.values() if domain is None or e['domain'] == domain]

    def parameters(self, name, params, *, references=False):
        return validate_schema(params, self.read(name)['input_schema'], references=references)

    def preflight(self, name, params):
        """Validate known domain semantics without opening a window/input device."""
        if self.read(name)['domain'] == 'hololive_dreams':
            from modular_agent.domains.hololive_dreams.capability_adapters import prepare_params
            prepare_params(self.root, name.split('.')[1], params, references=True)
