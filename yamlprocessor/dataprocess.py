#!/usr/bin/env python3
"""Read a YAML application configuration, process any includes.

Read a YAML application configuration, process any includes, and dump out the
result.
"""

from argparse import ArgumentParser
from errno import ENOENT
import os
import re
import sys

import yaml


class UnboundVariableError(ValueError):

    """An error raised on attempt to substitute an unbound variable."""

    def __repr__(self):
        return f"[UNBOUND VARIABLE] {self.args[0]}"

    __str__ = __repr__


class DataProcessor:
    """Process YAML and compatible data structure.

    Import sub-data-structure from include files.
    Process variable substitution in string values.

    Attributes:
      `.is_process_include`:
        (bool) Turn on/off include file processing.
      `.is_process_variable`:
        (bool) Turn on/off variable substitution.
      `.include_paths`:
        (list) Locations for searching include files.
      `.variable_map`:
        (dict) Mapping for variable substitutions. (Default=os.environ)
      `.unbound_variable_value`:
        (str) Value to substitute for unbound variables.
    """

    INCLUDE_DIRECTIVE = 'yaml::'

    RE_SUBSTITUTE = re.compile(
        r"\A"
        r"(?P<head>.*?)"
        r"(?P<escape>\\*)"
        r"(?P<symbol>"
        r"\$"
        r"(?P<brace_open>\{)?"
        r"(?P<name>[A-z_]\w*)"
        r"(?(brace_open)\})"
        r")"
        r"(?P<tail>.*)"
        r"\Z",
        re.M | re.S)

    def __init__(self):
        self.is_process_include = True
        self.is_process_variable = True
        self.include_paths = []
        self.variable_map = os.environ.copy()
        self.unbound_variable_value = None

    def process_data(self, in_filename: str, out_filename: str) -> None:
        """Process includes in input file and dump results in output file.

        :param in_filename: input file name.
        :param out_filename: output file name.
        """
        in_filename = self.get_filename(in_filename, [])
        root = yaml.safe_load(open(in_filename))
        stack = [[root, [in_filename]]]
        while stack:
            data, parent_filenames = stack.pop()
            data = self.process_variable(data)
            data = self.load_file(data)[0]
            items_iter = None
            if isinstance(data, list):
                items_iter = enumerate(data)
            elif isinstance(data, dict):
                items_iter = data.items()
            if items_iter is None:
                continue
            for key, item in items_iter:
                item = data[key] = self.process_variable(item)
                include_data, parent_filenames = self.load_file(
                    item, parent_filenames)
                if include_data != item:
                    item = data[key] = include_data
                if isinstance(item, dict) or isinstance(item, list):
                    stack.append([data[key], parent_filenames])
        yaml.dump(root, open(out_filename, 'w'), default_flow_style=False)

    def get_filename(self, filename: str, parent_filenames: list[str]) -> str:
        """Return absolute path of filename.

        If `filename` is a relative path, look for the file but looking the
        directories containing the parent files, then the current working
        directory, then each path in `.include_paths`.

        :param filename: File name to expand or return.
        :param parent_filenames: Stack of parent file names.
        """
        filename: str = os.path.expanduser(filename)
        if os.path.isabs(filename):
            return filename
        root_dirs = (
            list(os.path.abspath(os.path.dirname(f)) for f in parent_filenames)
            + [os.path.abspath('.')]
            + self.include_paths
        )
        for root_dir in root_dirs:
            name = os.path.join(root_dir, filename)
            if os.path.exists(name):
                return name
        raise OSError(ENOENT, filename, os.strerror(ENOENT))

    def load_file(
        self,
        value: object,
        parent_filenames: list[str] = None,
    ) -> tuple[object, str]:
        """Load data if value indicates the root file or an include file.

        :param value: Value that may contain file name to load.
        :param parent_filenames: Stack of parent file names.
        """
        if (
            self.is_process_include
            and isinstance(value, str)
            and value.startswith(self.INCLUDE_DIRECTIVE)
        ):
            include_filename = value[len(self.INCLUDE_DIRECTIVE):]
        else:
            include_filename = ''
        if include_filename:
            filename = self.get_filename(include_filename, parent_filenames)
            return (
                yaml.safe_load(open(filename)),
                parent_filenames + [filename],
            )
        else:
            return value, parent_filenames

    def process_variable(self, item: object) -> object:
        """Substitute environment variables into a string value.

        Return `item` as-is if not `.is_process_variable` or if `item` is not a
        string.

        For each `$NAME` and `${NAME}` in `item`, substitute with the value
        of the environment variable `NAME`.

        If `NAME` is not defined in the `.variable_map` and
        `.unbound_variable_value` is None, raise an `UnboundVariableError`.

        If `NAME` is not defined in the `.variable_map` and
        `.unbound_variable_value` is not None, substitute `NAME` with the value
        of `.unbound_variable_value`.

        :param item: Item to process. Do nothing if not a str.
        :return: Processed item on success.

        """
        if not self.is_process_variable or not isinstance(item, str):
            return item
        ret = ""
        try:
            tail = item.decode()
        except AttributeError:
            tail = item
        while tail:
            match = self.RE_SUBSTITUTE.match(tail)
            if match:
                groups = match.groupdict()
                substitute = groups["symbol"]
                if len(groups["escape"]) % 2 == 0:
                    if groups["name"] in self.variable_map:
                        substitute = self.variable_map[groups["name"]]
                    elif self.unbound_variable_value is not None:
                        substitute = str(self.unbound_variable_value)
                    else:
                        raise UnboundVariableError(groups["name"])
                ret += (
                    groups["head"]
                    + groups["escape"][0:len(groups["escape"]) // 2]
                    + substitute)
                tail = groups["tail"]
            else:
                ret += tail
                tail = ""
        return ret


def main(argv=None):
    parser = ArgumentParser(description=__file__)
    parser.add_argument(
        'in_filename',
        metavar='IN-FILE',
        default='-',
        help='Name of input file')
    parser.add_argument(
        'out_filename',
        metavar='OUT-FILE',
        default='-',
        help='Name of output file')
    parser.add_argument(
        '--include', '-I',
        dest='include_paths',
        metavar='PATH',
        action='append',
        default=[],
        help='Add search locations for item specified as relative paths')
    parser.add_argument(
        '--define', '-D',
        dest='defines',
        metavar='KEY=VALUE',
        action='append',
        default=[],
        help='Map KEY to VALUE for variable substitutions')
    parser.add_argument(
        '--undefine', '-U',
        dest='undefines',
        metavar='KEY',
        action='append',
        default=[],
        help='Unmap KEY for variable substitutions')
    parser.add_argument(
        '--no-environment', '-i',
        action='store_true',
        default=False,
        help='Do not use environment variables in variable substitutions')
    parser.add_argument(
        '--no-process-include',
        dest='is_process_include',
        action='store_false',
        default=True,
        help='Do not process include file instructions')
    parser.add_argument(
        '--no-process-variable',
        dest='is_process_variable',
        action='store_false',
        default=True,
        help='Do not process variable substitutions')
    args = parser.parse_args(argv)

    processor = DataProcessor()
    processor.is_process_include = args.is_process_include
    for item in args.include_paths:
        processor.include_paths.extend(item.split(os.path.pathsep))
    processor.is_process_variable = args.is_process_variable
    if args.no_environment:
        processor.variable_map.clear()
    for key in args.undefines:
        try:
            del processor.variable_map[key]
        except KeyError:
            pass
    for item in args.defines:
        key, value = item.split('=', 1)
        processor.variable_map[key] = value

    processor.process_data(args.in_filename, args.out_filename)


if __name__ == '__main__':
    main(sys.argv)
