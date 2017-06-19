from configparser import ParsingError
import os
import signal
import sys

from .argparse import arg, ArgParser, ConfigArgParser
from ..base import Singleton
from .. import logging


class AppBase(Singleton):
    __instance = None
    _commands = {}
    _argparser = ArgParser()

    def __init__(self):
        raise NotImplementedError()

    @classmethod
    def add_command(cls, name, command, args={}, description=None):
        assert type(args) == dict
        cls._argparser.add_group(name, help=description)
        for arg_name, value in args.items():
            cls.add_arg(arg_name, value, group=name)
        cls._commands[name] = command

    @classmethod
    def add_arg(cls, name, value, group=None):
        cls._argparser.add_arg(name, value, group)

    @classmethod
    def configure(cls, **kwargs):
        pass

    @classmethod
    def _parse_args(cls, command=None):
        return cls._argparser.parse(command=command)

    @classmethod
    def run(cls, command=None):
        cls.configure()
        command, command_args, common_args \
            = cls._parse_args(command)
        try:
            def handler(signum, frame):
                raise SystemExit("Signal(%d) received: "
                                 "The program %s will be closed"
                                 % (signum, __file__))
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
            os.umask(0)

            self = cls._get_instance()
            self._initialize(command, command_args, common_args)
            self._preprocess()
            self._process()
            self._postprocess()
            self._finalize()
        except Exception:
            logging.e("Exception occurred during execution:",
                      exc_info=True, stack_info=True)
        except SystemExit as e:
            logging.w(e)
        finally:
            logging.getLogger().finalize()
            sys.exit(0)

    @classmethod
    def _get_instance(cls):
        if cls.__instance is None:
            instance = object.__new__(cls)
            cls.__instance = instance
        return cls.__instance

    def _initialize(self, command, args, config):
        if hasattr(self, '_initialized') and self._initialized:
            return
        self._command = AppBase._commands[command]
        self._command_args = args
        self._config = config
        self._initialized = True

    def _preprocess(self):
        pass

    def _process(self):
        kwargs = self._command_args
        logging.d("App._process(self) called - command: {}, args: {}"
                  .format(self._command, kwargs))
        self._command(**kwargs)

    def _postprocess(self):
        pass

    def _finalize(self):
        pass


class App(AppBase):
    DEFAULT_APP_NAME = "teras.app"
    DEFAULT_CONFIG_FILE = "~/.teras.conf"
    app_name = ''
    _argparser = ConfigArgParser(DEFAULT_CONFIG_FILE)

    @staticmethod
    def _static_initialize():
        if hasattr(App, '_static_initialized') and App._static_initialized:
            return
        entry_script = sys.argv[0]
        basedir = os.path.dirname(os.path.realpath(entry_script))
        App.basedir = basedir
        App.entry_script = entry_script
        App.entry_point = os.path.join(basedir, entry_script)
        App._static_initialized = True

    @classmethod
    def configure(cls, **kwargs):
        if hasattr(cls, '_configured') and cls._configured:
            return
        cls.app_name = (kwargs['name'] if 'name' in kwargs
                        else cls.DEFAULT_APP_NAME)
        default_logdir = cls.basedir + '/logs'
        loglevel = (kwargs['loglevel']
                    if 'loglevel' in kwargs else logging.INFO)
        cls.add_arg('debug', arg('--debug',
                                 action='store_true',
                                 default=kwargs.get('debug', False),
                                 help='Enable debug mode'))
        cls.add_arg('logdir', arg('--logdir',
                                  type=str,
                                  default=kwargs.get('logdir', default_logdir),
                                  help='Log directory',
                                  metavar='DIR'))
        cls.add_arg('logoption', arg('--logoption',
                                     type=str,
                                     default=kwargs.get('logoption', 'a'),
                                     help='Log option: {a,d,h,n,w}',
                                     metavar='VALUE'))
        cls.add_arg('loglevel', loglevel)
        cls.add_arg('quiet', arg('--quiet',
                                 action='store_true',
                                 default=kwargs.get('quiet', False),
                                 help='execute quietly: '
                                 'does not print any message'))
        cls._configured = True

    @classmethod
    def _parse_args(cls, command=None):
        try:
            return cls._argparser.parse(command=command,
                                        section_prefix=cls.app_name)
        except (FileNotFoundError, ParsingError) as e:
            print(e, file=sys.stderr)
            sys.exit(0)

    def _preprocess(self):
        uname = os.uname()
        verbose = not(self._config['quiet'])

        if self._config['debug']:
            if (self._config['loglevel'] < logging.DISABLE
                    and self._config['loglevel'] > logging.DEBUG):
                self._config['loglevel'] = logging.DEBUG
        logger_name = App.entry_script
        logger_config = {
            'logdir': self._config['logdir'],
            'level': self._config['loglevel'],
            'verbosity': logging.TRACE if verbose else logging.DISABLE
        }
        for char in self._config['logoption']:
            if char == 'a':
                logger_config['filemode'] = 'a'
            elif char == 'd':
                logger_config['filelog'] = False
            elif char == 'h':
                logger_config['filesuffix'] = '-' + uname[1]
            elif char == 'n':
                logger_config['filemode'] = 'n'
            elif char == 'w':
                logger_config['filemode'] = 'w'
            else:
                raise ValueError("Invalid logoption specified: {}"
                                 .format(char))
        logging.AppLogger.configure(**logger_config)
        logger = logging.AppLogger(logger_name)
        logging.setRootLogger(logger)
        if not verbose:
            sys.stdout = sys.stderr = open(os.devnull, 'w')

        logger.v(str(os.uname()))
        logger.v("sys.argv: %s" % str(sys.argv))
        logger.v("app._config: {}".format(self._config))
        logger.i("*** [START] ***")

    def _postprocess(self):
        logging.i("*** [DONE] ***")


App._static_initialize()
