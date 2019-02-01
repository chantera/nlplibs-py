import math

from teras.dataset import Dataset
from teras.training import listeners
from teras.training.event import Dispatcher, TrainEvent


class Trainer(Dispatcher):
    EventClass = TrainEvent

    def __init__(self, optimizer, forward, loss_func, accuracy_func=None):
        super(Trainer, self).__init__()
        self._optimizer = optimizer
        self._forward = forward
        self._loss_func = loss_func
        self._acc_func = accuracy_func
        self._initialize()

    def _initialize(self):
        def update(optimizer, loss):
            # suppose chainer API
            optimizer.target.cleargrads()
            loss.backward()
            optimizer.update()
        self._update = update
        self._converter = None
        self._reporter = None

    def configure(self, config, **kwargs):
        assert isinstance(config, dict)
        config.update(kwargs)
        if 'update' in config:
            self._update = config['update']
        if 'hooks' in config:
            for event, hook in config['hooks'].items():
                self.add_hook(event, hook)
        if 'listeners' in config:
            for listener in config['listeners']:
                self.add_listener(listener)
        if 'converter' in config:
            self._converter = config['converter']

    def fit(self,
            x,
            y=None,
            batch_size=32,
            epochs=10,
            validation_data=None):
        if isinstance(x, Dataset):
            train_dataset = x
            assert y is None
        elif y is not None:
            train_dataset = Dataset(x, y)
        else:
            raise ValueError('incomplete input data: x={}, y={}'
                             .format(type(x), y))

        if validation_data:
            do_validation = True
            if isinstance(validation_data, Dataset):
                val_dataset = validation_data
            elif len(validation_data) == 2:
                val_x, val_y = validation_data
                val_dataset = Dataset(val_x, val_y)
            else:
                raise ValueError('When passing validation_data, '
                                 'it must be dataset or contain '
                                 '2 (x_val, y_val) items: {}'
                                 .format(type(validation_data)))
        else:
            do_validation = False

        self._reporter = listeners.Reporter()
        self.attach_listener(self._reporter, priority=150)
        if self._acc_func is not None:
            def _report_accuracy(data):
                listeners.report(
                    {"accuracy": self._acc_func(data['ys'], data['ts'])})
            self.add_hook(TrainEvent.BATCH_END, _report_accuracy)

        forward = self._forward
        if not callable(forward):
            if hasattr(self._forward, 'forward'):
                forward = self._forward.forward
            else:
                raise RuntimeError('`forward` is not callable')
        lossfun = self._loss_func
        convert = (self._converter if callable(self._converter)
                   else lambda x: x)

        history = []

        self.notify(TrainEvent.TRAIN_BEGIN)

        def main_loop():
            for epoch in range(1, epochs + 1):
                epoch_logs = {
                    'epoch': epoch,
                    'size': train_dataset.size,
                }
                self.notify(TrainEvent.EPOCH_BEGIN, epoch_logs)

                self._process(forward, train_dataset, lossfun,
                              convert, batch_size, epoch_logs)
                if do_validation:
                    self._process(forward, val_dataset, lossfun,
                                  convert, batch_size, epoch_logs, train=False)

                self.notify(TrainEvent.EPOCH_END, epoch_logs)

        if self._reporter is not None:
            with self._reporter:
                main_loop()
        else:
            main_loop()

        self.notify(TrainEvent.TRAIN_END)

        return history

    def _process(self,
                 forward,
                 dataset,
                 lossfun,
                 convert,
                 batch_size,
                 logs={}, train=True):
        logs = logs.copy()
        logs['size'] = dataset.size
        num_batches = math.ceil(logs['size'] / batch_size)
        logs['num_batches'] = num_batches
        logs['loss'] = None
        self.notify(TrainEvent.EPOCH_TRAIN_BEGIN
                    if train else TrainEvent.EPOCH_VALIDATE_BEGIN, logs)
        logs['loss'] = 0.0
        for batch_index, batch in enumerate(
                dataset.batch(batch_size, colwise=True, shuffle=train)):
            xs, ts = batch[:-1], batch[-1]
            if len(xs) == 1:
                xs = [convert(xs[0])]
            else:
                xs = convert(xs)
            ts = convert(ts)

            batch_logs = {
                'train': train,
                'batch_index': batch_index,
                'batch_size': len(ts),
                'xs': xs,
                'ts': ts,
                'ys': None,
                'loss': None,
                'num_batches': num_batches,
            }
            self.notify(TrainEvent.BATCH_BEGIN, batch_logs)

            ys = forward(*xs)
            loss = lossfun(ys, ts)

            batch_logs['ys'] = ys
            batch_logs['loss'] = loss.__float__()
            logs['loss'] += loss.__float__()

            if train:
                self._update(self._optimizer, loss)
            self.notify(TrainEvent.BATCH_END, batch_logs)
            del loss

        logs['loss'] /= num_batches
        self.notify(TrainEvent.EPOCH_TRAIN_END
                    if train else TrainEvent.EPOCH_VALIDATE_END, logs)
