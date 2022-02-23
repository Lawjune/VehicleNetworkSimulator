import can
import threading
import logging
_logger = logging.getLogger("CAN_transceiver")
_logger.setLevel(logging.DEBUG)

_ch = logging.StreamHandler()
_ch.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
_ch.setFormatter(formatter)
_logger.addHandler(_ch)

VCAN = 'vcan0'
SOCKET_CAN = 'socketcan'
BAUD_RATE_500K = 500000


class CanTransceiver(threading.Thread):
    def __init__(self, channel=VCAN, interface=SOCKET_CAN, bitrate=BAUD_RATE_500K,
                 filtered_msg_ids=None, record_last_msgs=False,
                 logger=_logger, logging_rec_msg=False):
        super(CanTransceiver, self).__init__()
        self.__class_name = self.__class__.__name__
        self.logger = logger
        self.__bus = can.interface.Bus(
            bustype=interface, channel=channel, bitrate=bitrate)
        self.__flag = threading.Event()  # Used to pause threading
        self.__flag.set()  # Set as True
        self.__running = threading.Event()  # Used to stop threading
        self.__running.set()
        self.__on_can_msg_callback = None
        self.__modify_tx_msg_callback = None
        self.__logging_rec_msg = logging_rec_msg

        self.__periodic_tx_msg_tasks = {}
        self.__filtered_msg_ids = filtered_msg_ids
        self.__set_can_filters()
        self.__last_rec_msgs = dict()
        self.__stopped_periodic_tx_msg_tasks = list()

        self.__record_last_msgs = record_last_msgs

    def __set_can_filters(self):
        if self.__filtered_msg_ids is None:
            self.logger.warning(
                f"[{self.__class_name}] CAN Filter has not been set!")
            return -1

        can_filters = []
        for msg_id in self.__filtered_msg_ids:
            self.logger.debug(
                f"[{self.__class_name}] Set can_filter for ID: {msg_id}")
            can_filter = {"can_id": msg_id,
                          "can_mask": 0xfff, "extended": False}
            can_filters.append(can_filter)

        self.__bus.set_filters(can_filters)

    def stop_periodic_tx_msg(self, msg_id):
        if not self.__is_sending(msg_id):
            self.logger.error(
                f'[{self.__class_name}] Message {msg_id} not in sending tasks.')
            return -1

        if msg_id in self.__stopped_periodic_tx_msg_tasks:
            self.logger.error(
                f'[{self.__class_name}] Message {msg_id} has been already stopped!')
            return -1

        task = self.__periodic_tx_msg_tasks[msg_id]
        task.stop()
        self.__stopped_periodic_tx_msg_tasks.append(msg_id)
        self.logger.debug(f"[{self.__class_name}] Stop sending {msg_id}.")
        return 0

    def start_periodic_tx_msg(self, msg_id):
        if not self.__is_sending(msg_id):
            self.logger.error(
                f'[{self.__class_name}] Message {msg_id} not in sending tasks.')
            return -1

        if msg_id in self.__stopped_periodic_tx_msg_tasks:
            task = self.__periodic_tx_msg_tasks[msg_id]
            task.start()
            self.__stopped_periodic_tx_msg_tasks.remove(msg_id)
            self.logger.debug(f"[{self.__class_name}] Start sending {msg_id}.")
            return 0
        else:
            self.logger.error(
                f"[{self.__class_name}] Message {msg_id} currently is running!")
            return -1

    def send_evt_msg(self, msg):
        self.__bus.send(msg)

    def add_periodic_tx_msg(self, msg, period):
        if not self.__is_can_msg(msg):
            return -1

        if self.__is_sending(msg.arbitration_id):
            self.logger.error(
                f'[{self.__class_name}] Message {msg.arbitration_id} already in sending tasks.')
            return -1

        self.logger.info(
            f'[{self.__class_name}] Start to send {msg} with period {period} seconds.')
        task = self.__bus.send_periodic(msgs=msg, period=period)
        if not isinstance(task, can.LimitedDurationCyclicSendTaskABC):
            self.logger.error(f"[{self.__class_name}] "
                              f"This interface doesn't seem to support LimitedDurationCyclicSendTaskABC")
            task.stop()
        self.__periodic_tx_msg_tasks[msg.arbitration_id] = task
        return task

    def run(self):

        while self.__running.isSet():
            self.__flag.wait()
            try:
                for msg in self.__bus:
                    self.__on_can_message(msg)
            except OSError:
                self.logger.info(
                    f"[{self.__class_name}] Successfully close CAN Transceiver")
            except ValueError:
                self.logger.info(
                    f"[{self.__class_name}] Successfully close CAN Transceiver")

    def pause(self):
        self.__flag.clear()  # Set as False to pause threading
        self.__stop_all_periodic_tasks()

    def resume(self):
        self.__flag.set()  # Set as True to resume threading
        self.__resume_all_periodic_tasks()

    def stop(self):
        self.__flag.set()
        self.__running.clear()
        self.__stop_all_periodic_tasks()
        self.__bus.shutdown()
        self.join()

    def __stop_all_periodic_tasks(self):
        for task in self.__periodic_tx_msg_tasks:
            try:
                self.__periodic_tx_msg_tasks[task].stop()
            except can.CanError as e:
                self.logger.warning(
                    f"[{self.__class_name}] Message {task} has been already stopped!")

    def __resume_all_periodic_tasks(self):
        for task in self.__periodic_tx_msg_tasks:
            self.__periodic_tx_msg_tasks[task].start()

    def __on_can_message(self, msg):
        if self.__logging_rec_msg:
            self.logger.debug(
                f'[{self.__class_name}] Receiving message: {msg}')

        if self.__on_can_msg_callback is not None:
            self.__on_can_msg_callback(msg)

        if self.__record_last_msgs:
            self.__last_rec_msgs[msg.arbitration_id] = msg

    def __modify_tx_msg(self, msg):
        if not self.__is_can_msg(msg):
            return -1

        if self.__periodic_tx_msg_tasks[msg.arbitration_id]:
            task = self.__periodic_tx_msg_tasks[msg.arbitration_id]
            task.modify_data(msg)
        else:
            self.logger.error(
                f'[{self.__class_name}] This message {msg} is not in the periodic_tx_msg_tasks!')

    def modify_tx_msg(self, msg):
        self.__modify_tx_msg(msg)
        if self.__modify_tx_msg_callback is not None:
            self.__modify_tx_msg_callback(msg)

    def set_on_can_msg_callback(self, callback):
        self.__on_can_msg_callback = callback

    def set_modify_tx_msg_callback(self, callback):
        self.__modify_tx_msg_callback = callback

    @property
    def periodic_tx_msg_tasks(self):
        return self.__periodic_tx_msg_tasks

    @property
    def last_rec_msgs(self):
        if self.__record_last_msgs:
            return self.__last_rec_msgs
        else:
            return -1

    def __is_can_msg(self, msg):
        if isinstance(msg, can.message.Message):
            return True
        else:
            self.logger.error(
                f'[{self.__class_name}] Invalid input CAN Message: {msg}')
            return -1

    def __is_sending(self, msg_id):
        return self.__periodic_tx_msg_tasks.__contains__(msg_id)


if __name__ == '__main__':
    import time
    can_trx = CanTransceiver(logging_rec_msg=True, filtered_msg_ids=[
                             0x002, 0x003], record_last_msgs=True)
    msg001 = can.Message(arbitration_id=0x001, data=[
                         1, 1, 1, 1, 1, 1], is_extended_id=False)
    msg002 = can.Message(arbitration_id=0x002, data=[
                         2, 2, 2, 2, 2, 2], is_extended_id=False)
    msg003 = can.Message(arbitration_id=0x003, data=[
                         3, 3, 3, 3, 3, 3], is_extended_id=False)
    can_trx.add_periodic_tx_msg(msg=msg001, period=0.5)
    can_trx.add_periodic_tx_msg(msg=msg002, period=1.0)
    can_trx.start()
    time.sleep(2)
    can_trx.add_periodic_tx_msg(msg=msg003, period=1.0)
    print("Stop msg003")
    can_trx.stop_periodic_tx_msg(0x003)
    time.sleep(3)
    print("Stop msg003 again!")
    can_trx.stop_periodic_tx_msg(0x003)
    time.sleep(3)
    print("Resume msg003")
    can_trx.start_periodic_tx_msg(0x003)
    time.sleep(2)
    print("Restart msg003")
    can_trx.start_periodic_tx_msg(0x003)
    time.sleep(2)
    can_trx.stop()
    print(can_trx.last_rec_msgs)
