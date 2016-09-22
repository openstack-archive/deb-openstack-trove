# Copyright 2015 Tesora Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import abc
import ast
import base64
import csv
import json
import re
import six
from six.moves.configparser import SafeConfigParser
import xmltodict
import yaml


from trove.common import utils as trove_utils


class StringConverter(object):
    """A passthrough string-to-object converter.
    """

    def __init__(self, object_mappings):
        """
        :param object_mappings:  string-to-object mappings
        :type object_mappings:   dict
        """
        self._object_mappings = object_mappings

    def to_strings(self, items):
        """Recursively convert collection items to strings.

        :returns:        Copy of the input collection with all items converted.
        """
        if trove_utils.is_collection(items):
            return map(self.to_strings, items)

        return self._to_string(items)

    def to_objects(self, items):
        """Recursively convert collection string to objects.

        :returns:        Copy of the input collection with all items converted.
        """
        if trove_utils.is_collection(items):
            return map(self.to_objects, items)

        return self._to_object(items)

    def _to_string(self, value):
        for k, v in self._object_mappings.items():
            if v is value:
                return k

        return str(value)

    def _to_object(self, value):
        # Return known mappings and quoted strings right away.
        if value in self._object_mappings:
            return self._object_mappings[value]
        elif (isinstance(value, six.string_types) and
              re.match("^'(.*)'|\"(.*)\"$", value)):
            return value

        try:
            return ast.literal_eval(value)
        except Exception:
            return value


@six.add_metaclass(abc.ABCMeta)
class StreamCodec(object):

    @abc.abstractmethod
    def serialize(self, data):
        """Serialize a Python object into a stream.
        """

    @abc.abstractmethod
    def deserialize(self, stream):
        """Deserialize stream data into a Python structure.
        """


class IdentityCodec(StreamCodec):
    """
    A basic passthrough codec.
    Does not modify the data in any way.
    """

    def serialize(self, data):
        return data

    def deserialize(self, stream):
        return stream


class YamlCodec(StreamCodec):
    """
    Read/write data from/into a YAML config file.

    a: 1
    b: {c: 3, d: 4}
    ...

    The above file content (flow-style) would be represented as:
    {'a': 1,
     'b': {'c': 3, 'd': 4,}
     ...
    }
    """

    def __init__(self, default_flow_style=False):
        """
        :param default_flow_style:  Use flow-style (inline) formatting of
                                    nested collections.
        :type default_flow_style:   boolean
        """
        self._default_flow_style = default_flow_style

    def serialize(self, dict_data):
        return yaml.dump(dict_data, Dumper=self.dumper,
                         default_flow_style=self._default_flow_style)

    def deserialize(self, stream):
        return yaml.load(stream, Loader=self.loader)

    @property
    def loader(self):
        return yaml.loader.Loader

    @property
    def dumper(self):
        return yaml.dumper.Dumper


class SafeYamlCodec(YamlCodec):
    """
    Same as YamlCodec except that it uses safe Loader and Dumper which
    encode Unicode strings and produce only basic YAML tags.
    """

    def __init__(self, default_flow_style=False):
        super(SafeYamlCodec, self).__init__(
            default_flow_style=default_flow_style)

    @property
    def loader(self):
        return yaml.loader.SafeLoader

    @property
    def dumper(self):
        return yaml.dumper.SafeDumper


class IniCodec(StreamCodec):
    """
    Read/write data from/into an ini-style config file.

    [section_1]
    key = value
    key = value
    ...

    [section_2]
    key = value
    key = value
    ...

    The above file content would be represented as:
    {'section_1': {'key': value, 'key': value, ...},
     'section_2': {'key': value, 'key': value, ...}
     ...
    }
    """

    def __init__(self, default_value=None, comment_markers=('#', ';')):
        """
        :param default_value:  Default value for keys with no value.
                               If set, all keys are written as 'key = value'.
                               The key is written without trailing '=' if None.
        :type default_value:   object
        """
        self._default_value = default_value
        self._comment_markers = comment_markers

    def serialize(self, dict_data):
        parser = self._init_config_parser(dict_data)
        output = six.StringIO()
        parser.write(output)

        return output.getvalue()

    def deserialize(self, stream):
        parser = self._init_config_parser()
        parser.readfp(self._pre_parse(stream))

        return {s: {k:
                    StringConverter({None: self._default_value}).to_objects(v)
                    for k, v in parser.items(s, raw=True)}
                for s in parser.sections()}

    def _pre_parse(self, stream):
        buf = six.StringIO()
        for line in six.StringIO(stream):
            # Ignore commented lines.
            if not line.startswith(self._comment_markers):
                # Strip leading and trailing whitespaces from each line.
                buf.write(line.strip() + '\n')

        # Rewind the output buffer.
        buf.flush()
        buf.seek(0)

        return buf

    def _init_config_parser(self, sections=None):
        parser = SafeConfigParser(allow_no_value=True)
        if sections:
            for section in sections:
                parser.add_section(section)
                for key, value in sections[section].items():
                    str_val = StringConverter(
                        {self._default_value: None}).to_strings(value)
                    parser.set(section, key,
                               str(str_val) if str_val is not None
                               else str_val)

        return parser


class PropertiesCodec(StreamCodec):
    """
    Read/write data from/into a property-style config file.

    key1 k1arg1 k1arg2 ... k1argN
    key2 k2arg1 k2arg2 ... k2argN
    key3 k3arg1 k3arg2 ...
    key3 k3arg3 k3arg4 ...
    ...

    The above file content would be represented as:
    {'key1': [k1arg1, k1arg2 ... k1argN],
     'key2': [k2arg1, k2arg2 ... k2argN]
     'key3': [[k3arg1, k3arg2, ...], [k3arg3, k3arg4, ...]]
     ...
    }
    """

    QUOTING_MODE = csv.QUOTE_MINIMAL
    STRICT_MODE = False
    SKIP_INIT_SPACE = True

    def __init__(self, delimiter=' ', comment_markers=('#'),
                 unpack_singletons=True, string_mappings=None):
        """
        :param delimiter:         A one-character used to separate fields.
        :type delimiter:          string

        :param empty_value:       Value to represent None in the output.
        :type empty_value:        object

        :param comment_markers:   List of comment markers.
        :type comment_markers:    list

        :param unpack_singletons: Whether to unpack singleton collections
                                  (collections with only a single value).
        :type unpack_singletons:  boolean

        :param string_mappings:   User-defined string representations of
                                  Python objects.
        :type string_mappings:    dict
        """
        self._delimiter = delimiter
        self._comment_markers = comment_markers
        self._string_converter = StringConverter(string_mappings or {})
        self._unpack_singletons = unpack_singletons

    def serialize(self, dict_data):
        output = six.StringIO()
        writer = csv.writer(output, delimiter=self._delimiter,
                            quoting=self.QUOTING_MODE,
                            strict=self.STRICT_MODE,
                            skipinitialspace=self.SKIP_INIT_SPACE)

        for key, value in dict_data.items():
            writer.writerows(self._to_rows(key, value))

        return output.getvalue()

    def deserialize(self, stream):
        reader = csv.reader(six.StringIO(stream),
                            delimiter=self._delimiter,
                            quoting=self.QUOTING_MODE,
                            strict=self.STRICT_MODE,
                            skipinitialspace=self.SKIP_INIT_SPACE)

        return self._to_dict(reader)

    def _to_dict(self, reader):
        data_dict = {}
        for row in reader:
            if row:
                key = row[0].strip()
                # Ignore comment lines.
                if not key.strip().startswith(self._comment_markers):
                    items = self._string_converter.to_objects(
                        [v if v else None for v in
                         map(self._strip_comments, row[1:])])
                    current = data_dict.get(key)
                    if current is not None:
                        current.append(trove_utils.unpack_singleton(items)
                                       if self._unpack_singletons else items)
                    else:
                        data_dict.update({key: [items]})

        if self._unpack_singletons:
            # Unpack singleton values.
            for k, v in data_dict.items():
                data_dict.update({k: trove_utils.unpack_singleton(v)})

        return data_dict

    def _strip_comments(self, value):
        # Strip in-line comments.
        for marker in self._comment_markers:
            value = value.split(marker)[0]
        return value.strip()

    def _to_rows(self, header, items):
        rows = []
        if trove_utils.is_collection(items):
            if any(trove_utils.is_collection(item) for item in items):
                # This is multi-row property.
                for item in items:
                    rows.extend(self._to_rows(header, item))
            else:
                # This is a single-row property with multiple arguments.
                rows.append(self._to_list(
                    header, self._string_converter.to_strings(items)))
        else:
            # This is a single-row property with only one argument.
            rows.append(
                self._string_converter.to_strings(
                    self._to_list(header, items)))

        return rows

    def _to_list(self, *items):
        container = []
        for item in items:
            if trove_utils.is_collection(item):
                # This item is a nested collection - unpack it.
                container.extend(self._to_list(*item))
            else:
                # This item is not a collection - append it to the list.
                container.append(item)

        return container


class KeyValueCodec(StreamCodec):
    """
    Read/write data from/into a simple key=value file.

    key1=value1
    key2=value2
    key3=value3
    ...

    The above file content would be represented as:
    {'key1': 'value1',
     'key2': 'value2',
     'key3': 'value3',
     ...
    }
    """

    BOOL_PYTHON = 0  # True, False
    BOOL_LOWER = 1   # true, false
    BOOL_UPPER = 2   # TRUE, FALSE

    def __init__(self, delimiter='=',
                 comment_marker='#',
                 line_terminator='\r\n',
                 value_quoting=False,
                 value_quote_char="'",
                 bool_case=BOOL_PYTHON,
                 big_ints=False,
                 hidden_marker=None):
        """
        :param delimiter:        string placed between key and value
        :param comment_marker:   string indicating comment line in file
        :param line_terminator:  string placed between lines
        :param value_quoting:    whether or not to quote string values
        :param value_quote_char: character used to quote string values
        :param bool_case:        BOOL_* setting case of bool values
        :param big_ints:         treat K/M/G at the end of ints as an int
        :param hidden_marker:    pattern prefixing hidden param
        """
        self._delimeter = delimiter
        self._comment_marker = comment_marker
        self._line_terminator = line_terminator
        self._value_quoting = value_quoting
        self._value_quote_char = value_quote_char
        self._bool_case = bool_case
        self._big_ints = big_ints
        self._hidden_marker = hidden_marker

    def serialize(self, dict_data):
        lines = []
        for k, v in dict_data.items():
            lines.append(k + self._delimeter + self.serialize_value(v))
        return self._line_terminator.join(lines)

    def deserialize(self, stream):
        lines = stream.split(self._line_terminator)
        result = {}
        for line in lines:
            line = line.lstrip().rstrip()
            if line == '' or line.startswith(self._comment_marker):
                continue
            k, v = re.split(re.escape(self._delimeter), line, 1)
            if self._value_quoting and v.startswith(self._value_quote_char):
                # remove trailing comments
                v = re.sub(r'%s *%s.*$' % ("'", '#'), '', v)
                v = v.lstrip(
                    self._value_quote_char).rstrip(
                    self._value_quote_char)
            else:
                # remove trailing comments
                v = re.sub('%s.*$' % self._comment_marker, '', v)
            if self._hidden_marker and v.startswith(self._hidden_marker):
                continue
            result[k.strip()] = v
        return result

    def serialize_value(self, value):
        if isinstance(value, bool):
            if self._bool_case == self.BOOL_PYTHON:
                value = str(value)
            elif self._bool_case == self.BOOL_LOWER:
                value = str(value).lower()
            elif self._bool_case == self.BOOL_UPPER:
                value = str(value).upper()
        if self.should_quote_value(value):
            value = self._value_quote_char + value + self._value_quote_char
        return str(value)

    def should_quote_value(self, value):
        if not self._value_quoting:
            return False
        if isinstance(value, bool) or isinstance(value, int):
            return False
        if value.lower() in ['true', 'false']:
            return False
        try:
            int(value)
            return False
        except ValueError:
            pass
        if self._big_ints and re.match(r'\d+[kKmMgGtTpP]', value):
            return False
        return True


class JsonCodec(StreamCodec):

    def serialize(self, dict_data):
        return json.dumps(dict_data)

    def deserialize(self, stream):
        return json.load(six.StringIO(stream))


class Base64Codec(StreamCodec):
    """Serialize (encode) and deserialize (decode) using the base64 codec.
    To read binary data from a file and b64encode it, used the decode=False
    flag on operating_system's read calls.  Use encode=False to decode
    binary data before writing to a file as well.
    """

    def serialize(self, data):

        try:
            # py27str - if we've got text data, this should encode it
            # py27aa/py34aa - if we've got a bytearray, this should work too
            encoded = str(base64.b64encode(data).decode('utf-8'))
        except TypeError:
            # py34str - convert to bytes first, then we can encode
            data_bytes = bytes([ord(item) for item in data])
            encoded = base64.b64encode(data_bytes).decode('utf-8')
        return encoded

    def deserialize(self, stream):

        # py27 & py34 seem to understand bytearray the same
        return bytearray([item for item in base64.b64decode(stream)])


class XmlCodec(StreamCodec):

    def __init__(self, encoding='utf-8'):
        self._encoding = encoding

    def serialize(self, dict_data):
        return xmltodict.unparse(
            dict_data, output=None, encoding=self._encoding, pretty=True)

    def deserialize(self, stream):
        return xmltodict.parse(stream, encoding=self._encoding)
