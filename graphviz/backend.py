"""Execute rendering subprocesses and open files in viewer."""

import errno
import logging
import os
import platform
import pathlib
import re
import subprocess
import sys
import typing

from . import tools

__all__ = ['DOT_BINARY', 'UNFLATTEN_BINARY',
           'ENGINES', 'FORMATS', 'RENDERERS', 'FORMATTERS',
           'ExecutableNotFound', 'RequiredArgumentError'
           'render', 'pipe', 'unflatten', 'version', 'view']

#: :class:`pathlib.Path` of layout command (``Path('dot')``).
DOT_BINARY = pathlib.Path('dot')

#: :class:`pathlib.Path` of unflatten command (``Path('unflatten')``).
UNFLATTEN_BINARY = pathlib.Path('unflatten')

ENGINES = {'dot', # http://www.graphviz.org/pdf/dot.1.pdf
           'neato',
           'twopi',
           'circo',
           'fdp',
           'sfdp',
           'patchwork',
           'osage'}


FORMATS = {'bmp', # http://www.graphviz.org/doc/info/output.html
           'canon', 'dot', 'gv', 'xdot', 'xdot1.2', 'xdot1.4',
           'cgimage',
           'cmap',
           'eps',
           'exr',
           'fig',
           'gd', 'gd2',
           'gif',
           'gtk',
           'ico',
           'imap', 'cmapx',
           'imap_np', 'cmapx_np',
           'ismap',
           'jp2',
           'jpg', 'jpeg', 'jpe',
           'json', 'json0', 'dot_json', 'xdot_json',  # Graphviz 2.40
           'pct', 'pict',
           'pdf',
           'pic',
           'plain', 'plain-ext',
           'png',
           'pov',
           'ps',
           'ps2',
           'psd',
           'sgi',
           'svg', 'svgz',
           'tga',
           'tif', 'tiff',
           'tk',
           'vml', 'vmlz',
           'vrml',
           'wbmp',
           'webp',
           'xlib',
           'x11'}

RENDERERS = {'cairo',  # $ dot -T:
             'dot',
             'fig',
             'gd',
             'gdiplus',
             'map',
             'pic',
             'pov',
             'ps',
             'svg',
             'tk',
             'vml',
             'vrml',
             'xdot'}

FORMATTERS = {'cairo',
              'core',
              'gd',
              'gdiplus',
              'gdwbmp',
              'xlib'}

ENCODING = 'utf-8'

PLATFORM = platform.system().lower()


log = logging.getLogger(__name__)


class ExecutableNotFound(RuntimeError):
    """Exception raised if the Graphviz executable is not found."""

    _msg = ('failed to execute {!r}, '
            'make sure the Graphviz executables are on your systems\' PATH')

    def __init__(self, args):
        super().__init__(self._msg.format(*args))


class RequiredArgumentError(Exception):
    """Exception raised if a required argument is missing (i.e. ``None``)."""


class CalledProcessError(subprocess.CalledProcessError):

    def __str__(self):
        s = super().__str__()
        return f'{s} [stderr: {self.stderr!r}]'


def command(engine: str, format_: str, filepath=None,
            renderer: typing.Optional[str] = None,
            formatter: typing.Optional[str] = None):
    """Return args list for ``subprocess.Popen``
        and name of the rendered file."""
    if formatter is not None and renderer is None:
        raise RequiredArgumentError('formatter given without renderer')

    if engine not in ENGINES:
        raise ValueError(f'unknown engine: {engine!r}')
    if format_ not in FORMATS:
        raise ValueError(f'unknown format: {format_!r}')
    if renderer is not None and renderer not in RENDERERS:
        raise ValueError(f'unknown renderer: {renderer!r}')
    if formatter is not None and formatter not in FORMATTERS:
        raise ValueError(f'unknown formatter: {formatter!r}')

    output_format = [f for f in (format_, renderer, formatter) if f is not None]
    output_format_flag = ':'.join(output_format)
    cmd = [DOT_BINARY, f'-K{engine}', f'-T{output_format_flag}']

    if filepath is None:
        rendered = None
    else:
        cmd.extend(['-O', filepath])
        suffix = '.'.join(reversed(output_format))
        rendered = f'{filepath}.{suffix}'

    return cmd, rendered


if PLATFORM == 'windows':  # pragma: no cover
    def get_startupinfo():
        """Return subprocess.STARTUPINFO instance
            hiding the console window."""
        startupinfo = subprocess.STARTUPINFO()  # pytype: disable=module-attr
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # pytype: disable=module-attr
        startupinfo.wShowWindow = subprocess.SW_HIDE  # pytype: disable=module-attr
        return startupinfo
else:
    def get_startupinfo():
        """Return None for startupinfo argument of ``subprocess.Popen``."""
        return None


def subprocess_run(cmd, *args, **kwargs):
    log.debug('run %r', cmd)
    try:        
        return subprocess.run(cmd, *args,
                              startupinfo=get_startupinfo(), **kwargs)
    except OSError as e:
        if e.errno == errno.ENOENT:
            raise ExecutableNotFound(cmd) from e
        else:
            raise


def run(cmd, input: typing.Optional[bytes] = None,
        capture_output: bool = False,
        check: bool = False,
        quiet: bool = False,
        **kwargs) -> typing.Tuple[bytes, bytes]:
    """Run the command described by cmd
            and return its ``(stdout, stderr)`` tuple."""
    log.debug('run %r', cmd)

    if input is not None:
        kwargs['stdin'] = subprocess.PIPE

    if capture_output:  # Python 3.6 compat
        kwargs['stdout'] = kwargs['stderr'] = subprocess.PIPE

    try:
        proc = subprocess.Popen(cmd, startupinfo=get_startupinfo(), **kwargs)
    except OSError as e:
        if e.errno == errno.ENOENT:
            raise ExecutableNotFound(cmd) from e
        else:
            raise

    if input is not None and iter(input) is input:
        stdin_write = proc.stdin.write
        for chunk in input:
            stdin_write(chunk)
        input = None

    out, err = proc.communicate(input)

    if not quiet and err:
        err_encoding = (getattr(sys.stderr, 'encoding', None)
                        or sys.getdefaultencoding())
        sys.stderr.write(err.decode(err_encoding))
        sys.stderr.flush()

    if check and proc.returncode:
        raise CalledProcessError(proc.returncode, cmd,
                                 output=out, stderr=err)

    return out, err


def render(engine: str, format: str, filepath,
           renderer: typing.Optional[str] = None,
           formatter: typing.Optional[str] = None,
           quiet: bool = False) -> str:
    """Render file with Graphviz ``engine`` into ``format``,
        return result filename.

    Args:
        engine: Layout engine for rendering (``'dot'``, ``'neato'``, ...).
        format: Output format for rendering (``'pdf'``, ``'png'``, ...).
        filepath: Path to the DOT source file to render.
        renderer: Output renderer (``'cairo'``, ``'gd'``, ...).
        formatter: Output formatter (``'cairo'``, ``'gd'``, ...).
        quiet: Suppress ``stderr`` output from the layout subprocess.

    Returns:
        The (possibly relative) path of the rendered file.

    Raises:
        ValueError: If ``engine``, ``format``, ``renderer``, or ``formatter``
            are not known.
        graphviz.RequiredArgumentError: If ``formatter`` is given
            but ``renderer`` is None.
        graphviz.ExecutableNotFound: If the Graphviz 'dot' executable
            is not found.
        subprocess.CalledProcessError: If the returncode (exit status)
            of the rendering 'dot' subprocess is non-zero.

    Note:
        The layout command is started from the directory of ``filepath``,
        so that references to external files
        (e.g. ``[image=images/camelot.png]``)
        can be given as paths relative to the DOT source file.
    """
    dirname, filename = os.path.split(filepath)
    del filepath

    cmd, rendered = command(engine, format, filename, renderer, formatter)
    assert rendered is not None, 'rendered is None only if filepath is as well'
    if dirname:
        cwd = dirname
        rendered = os.path.join(dirname, rendered)
    else:
        cwd = None

    run(cmd, capture_output=True, cwd=cwd, check=True, quiet=quiet)
    return rendered


def pipe(engine: str, format: str, data: bytes,
         renderer: typing.Optional[str] = None,
         formatter: typing.Optional[str] = None,
         quiet: bool = False) -> bytes:
    """Return ``data`` piped through Graphviz ``engine`` into ``format``.

    Args:
        engine: Layout engine for rendering (``'dot'``, ``'neato'``, ...).
        format: Output format for rendering (``'pdf'``, ``'png'``, ...).
        data: Binary (encoded) DOT source bytes to render.
        renderer: Output renderer (``'cairo'``, ``'gd'``, ...).
        formatter: Output formatter (``'cairo'``, ``'gd'``, ...).
        quiet: Suppress ``stderr`` output from the layout subprocess.

    Returns:
        Binary (encoded) stdout of the layout command.

    Raises:
        ValueError: If ``engine``, ``format``, ``renderer``, or ``formatter``
            are not known.
        graphviz.RequiredArgumentError: If ``formatter`` is given
            but ``renderer`` is None.
        graphviz.ExecutableNotFound: If the Graphviz 'dot' executable
            is not found.
        subprocess.CalledProcessError: If the returncode (exit status)
            of the rendering 'dot' subprocess is non-zero.

    Example:
        >>> import graphviz
        >>> graphviz.pipe('dot', 'svg', b'graph { hello -- world }')
        b'<?xml version=...'

    Note:
        The layout command is started from the current directory.
    """
    cmd, _ = command(engine, format, None, renderer, formatter)
    out, _ = run(cmd, input=data, capture_output=True, check=True, quiet=quiet)
    return out


def unflatten(source: str,
              stagger: typing.Optional[int] = None,
              fanout: bool  = False,
              chain: typing.Optional[int] = None,
              encoding: str = ENCODING) -> str:
    """Return DOT ``source`` piped through Graphviz *unflatten* preprocessor.

    Args:
        source: DOT source to process
            (improve layout aspect ratio).
        stagger: Stagger the minimum length of leaf edges
            between 1 and this small integer.
        fanout: Fanout nodes with indegree = outdegree = 1
            when staggering (requires ``stagger``).
        chain: Form disconnected nodes into chains of up to this many nodes.
        encoding: Encoding to encode unflatten stdin and decode its stdout.

    Returns:
        Decoded stdout of the Graphviz unflatten command.

    Raises:
        graphviz.RequiredArgumentError: If ``fanout`` is given
            but no ``stagger``.
        graphviz.ExecutableNotFound: If the Graphviz 'unflatten' executable
            is not found.
        subprocess.CalledProcessError: If the returncode (exit status)
            of the unflattening 'unflatten' subprocess is non-zero.

    See also:
        https://www.graphviz.org/pdf/unflatten.1.pdf
    """
    if fanout and stagger is None:
        raise RequiredArgumentError('fanout given without stagger')

    cmd = [UNFLATTEN_BINARY]
    if stagger is not None:
        cmd += ['-l', str(stagger)]
    if fanout:
        cmd.append('-f')
    if chain is not None:
        cmd += ['-c', str(chain)]

    raw = source.encode(encoding)
    out, _ = run(cmd, input=raw, capture_output=True)
    return out.decode(encoding)


def version() -> typing.Tuple[int, ...]:
    """Return the version number tuple
        from the ``stderr`` output of ``dot -V``.

    Returns:
        Two, three, or four ``int`` version ``tuple``.

    Raises:
        graphviz.ExecutableNotFound: If the Graphviz executable is not found.
        subprocess.CalledProcessError: If the exit status is non-zero.
        RuntimeError: If the output cannot be parsed into a version number.

    Example:
        >>> import graphviz
        >>> graphviz.version()
        (...)

    Note:
        Ignores the ``~dev.<YYYYmmdd.HHMM>`` portion of development versions.

    See also:
        Graphviz Release version entry format:
        https://gitlab.com/graphviz/graphviz/-/blob/f94e91ba819cef51a4b9dcb2d76153684d06a913/gen_version.py#L17-20
    """
    cmd = [DOT_BINARY, '-V']
    log.debug('run %r', cmd)
    proc = subprocess_run(cmd, check=True,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT,
                          encoding='ascii')

    ma = re.search(r'graphviz version'
                   r' '
                   r'(\d+)\.(\d+)'
                   r'(?:\.(\d+)'
                       r'(?:'
                           r'~dev\.\d{8}\.\d{4}'
                           r'|'
                           r'\.(\d+)'
                       r')?'
                   r')?'
                   r' ', proc.stdout)
    if ma is None:
        raise RuntimeError(f'cannot parse {cmd!r} output: {proc.stdout!r}')

    return tuple(int(d) for d in ma.groups() if d is not None)


def view(filepath, quiet: bool = False) -> None:
    """Open filepath with its default viewing application
        (platform-specific).

    Args:
        filepath: Path to the file to open in viewer.
        quiet: Suppress ``stderr`` output
            from the viewer process (ineffective on Windows).

    Returns:
        ``None``

    Raises:
        RuntimeError: If the current platform is not supported.

    Note:
        There is no option to wait for the application to close,
        and no way to retrieve the application's exit status.
    """
    try:
        view_func = getattr(view, PLATFORM)
    except AttributeError:
        raise RuntimeError(f'platform {PLATFORM!r} not supported')
    view_func(filepath, quiet=quiet)


@tools.attach(view, 'darwin')
def view_darwin(filepath, *, quiet: bool) -> None:
    """Open filepath with its default application (mac)."""
    cmd = ['open', filepath]
    log.debug('view: %r', cmd)
    kwargs = {'stderr': subprocess.DEVNULL} if quiet else {}
    subprocess.Popen(cmd, **kwargs)


@tools.attach(view, 'linux')
@tools.attach(view, 'freebsd')
def view_unixoid(filepath, *, quiet: bool) -> None:
    """Open filepath in the user's preferred application (linux, freebsd)."""
    cmd = ['xdg-open', filepath]
    log.debug('view: %r', cmd)
    kwargs = {'stderr': subprocess.DEVNULL} if quiet else {}
    subprocess.Popen(cmd, **kwargs)


@tools.attach(view, 'windows')
def view_windows(filepath, *, quiet: bool) -> None:
    """Start filepath with its associated application (windows)."""
    # TODO: implement quiet=True
    filepath = os.path.normpath(filepath)
    log.debug('view: %r', filepath)
    os.startfile(filepath)  # pytype: disable=module-attr
