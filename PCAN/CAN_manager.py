from CAN_message import CanMessage
from CAN_transceiver import CanTransceiver

import cantools
import logging
import json

_logger = logging.getLogger("CAN_manager")
_logger.setLevel(logging.DEBUG)

_ch = logging.StreamHandler()
_ch.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    f'%(asctime)s - %(name)s - %(levelname)s - %(message)s')
_ch.setFormatter(formatter)
_logger.addHandler(_ch)


class CanManager:

    VCAN = 'vcan0'
    PCAN = 'can0'
    SOCKET_CAN = 'socketcan'
    BAUD_RATE_500K = 500000
    BAUD_RATE_125K = 125000

    def __init__(self,
                 dbc_path, init_tx_msgs_json_path, last_modified_tx_msgs_json_path=None,
                 channel=VCAN, interface=SOCKET_CAN, bitrate=BAUD_RATE_500K, default_can_period=0.5,
                 logging_rec_msg=False, record_last_msgs=False,
                 target_names=None,
                 logger=_logger):
        self.logger = logger
        self.__dbc = cantools.database.load_file(dbc_path)
        self.__default_can_period = default_can_period

        """
        Init for target messages management 
        """
        self.__all_messages = self.__dbc.messages
        self.__target_names = target_names
        self.__target_messages = None
        self.__target_message_ids = None
        self.__set_target_messages()

        """
        Init for broadcasting CAN messages
        """
        self.__init_tx_msgs_json_path = init_tx_msgs_json_path
        self.__last_modified_tx_msgs_json_path = last_modified_tx_msgs_json_path
        self.__init_tx_msgs_dict = None
        self.__last_modified_tx_msgs_dict = None
        self.__msgs_bundle = dict()
        self.__get_init_msgs_from_json()
        self.__construct_init_messages()

        """
        Init CAN Transceiver 
        """
        self.__record_last_msgs = record_last_msgs
        self.__logging_rec_msgs_enabled = logging_rec_msg
        self.__can_trx = CanTransceiver(channel=channel,
                                        interface=interface,
                                        bitrate=bitrate,
                                        filtered_msg_ids=self.__target_message_ids,
                                        record_last_msgs=self.__record_last_msgs,
                                        logger=logger)
        self.__external_on_can_msg_callback = None
        self.__external_modified_msg_callback = None

    """
    Init broadcasting CAN messages
    """

    def __construct_init_messages(self):
        for msg_id_str in self.__init_tx_msgs_dict:
            msg_id = self.convert_string_to_hex(msg_id_str)
            msg = CanMessage(dbc=self.__dbc, can_id=msg_id,
                             init_can_data=self.__init_tx_msgs_dict[msg_id_str],
                             logger=self.logger)
            self.__msgs_bundle[msg_id] = msg

    def __get_init_msgs_from_json(self):
        with open(self.__init_tx_msgs_json_path, 'r') as f:
            self.__init_tx_msgs_dict = json.load(f)
            self.__last_modified_tx_msgs_dict = self.__init_tx_msgs_dict.copy()

    def __load_init_msgs_to_can_trx(self):

        for msg_id in self.__msgs_bundle:
            if self.__msgs_bundle[msg_id].period:
                self.__can_trx.add_periodic_tx_msg(msg=self.__msgs_bundle[msg_id].can_msg,
                                                   period=self.__msgs_bundle[msg_id].period / 1000)
            else:
                self.__can_trx.add_periodic_tx_msg(msg=self.__msgs_bundle[msg_id].can_msg,
                                                   period=self.__default_can_period / 1000)

    """
    CAN Transceiver Callback
    """

    def __on_can_msg_callback(self, msg):
        msg_id = msg.arbitration_id
        dbc_msg = self.__dbc.get_message_by_frame_id(msg_id)
        data = dbc_msg.decode(msg.data)
        if self.__logging_rec_msgs_enabled:
            self.logger.debug(
                f"[{self.__class__}] Receiving {hex(msg_id)}: {data}")

        if self.__external_on_can_msg_callback:
            self.__external_on_can_msg_callback(msg)

    def __modified_tx_msg_callback(self, msg):
        msg_id = msg.arbitration_id
        dbc_msg = self.__dbc.get_message_by_frame_id(msg_id)
        data = dbc_msg.decode(msg.data)
        self.logger.info(
            f"[{self.__class__}] Modified {hex(msg_id)} as {data}")
        self.__update_msg_dict(msg_id=msg_id, decoded_data=data)

        if self.__external_modified_msg_callback:
            self.__external_modified_msg_callback(msg)

    def __update_msg_dict(self, msg_id, decoded_data):
        self.__last_modified_tx_msgs_dict[hex(msg_id)] = decoded_data

    def __store_last_modified_msg_json(self):
        with open(self.__last_modified_tx_msgs_json_path, "w") as output:
            json.dump(self.__last_modified_tx_msgs_dict, output)

    """
    Target messages management 
    """

    def __set_target_messages(self):
        if self.__target_names:
            if type(self.__target_names) != list:
                target_names = [self.__target_names]
                self.__target_names = target_names

            self.__target_messages = \
                list(filter(lambda msg: all(sender in msg.senders for sender in self.__target_names),
                            self.__all_messages))
            self.__target_message_ids = list(
                map(lambda msg: msg.frame_id, self.__target_messages))
        else:
            pass

    @staticmethod
    def convert_string_to_hex(msg_id):
        return int(msg_id, 16)

    def __is_in_msg_bundle(self, msg_id):
        return self.__msgs_bundle.__contains__(msg_id)

    """
    Exposed APIs
    """

    def decode_msg(self, msg):
        msg_id = msg.arbitration_id
        dbc_msg = self.__dbc.get_message_by_frame_id(msg_id)
        data = dbc_msg.decode(msg.data)
        return data

    def add_init_msg(self, can_msg):
        if not isinstance(can_msg, CanMessage):
            raise TypeError(
                f"[{self.__class__}] Input can_msg is not an instance of CanMessage!")

        msg_id = can_msg.can_id
        if not self.__is_in_msg_bundle(msg_id):
            self.__msgs_bundle[msg_id] = can_msg

    def add_init_msgs(self, can_msg_list):
        for msg in can_msg_list:
            self.__msgs_bundle[msg.can_id] = msg

    def add_tx_msg(self, can_msg):
        if not isinstance(can_msg, CanMessage):
            raise TypeError(
                f"[{self.__class__}] Input can_msg is not an instance of CanMessage!")

        self.__can_trx.add_periodic_tx_msg(
            msg=can_msg.can_msg, period=can_msg.period / 1000)
        msg_id = can_msg.can_id
        if not self.__is_in_msg_bundle(msg_id):
            self.__msgs_bundle[msg_id] = can_msg

    def add_tx_msgs(self, can_msg_list):
        for msg in can_msg_list:
            self.add_tx_msg(msg)

    def start(self):
        self.__can_trx.set_on_can_msg_callback(self.__on_can_msg_callback)
        self.__can_trx.set_modify_tx_msg_callback(
            self.__modified_tx_msg_callback)
        self.__load_init_msgs_to_can_trx()
        self.__can_trx.start()

    def stop(self):
        self.__store_last_modified_msg_json()
        self.__can_trx.stop()

    def modify_tx_msg(self, msg_id, can_data, event=False, **signals):
        msg_id = self.convert_string_to_hex(msg_id)
        if self.__is_in_msg_bundle(msg_id):
            msg = self.__msgs_bundle[msg_id]
            msg.modify_signals(can_data=can_data, **signals)

            if event:
                self.logger.debug(
                    f"[{self.__class__}] Send event message {hex(msg_id)} from msg_bundle_list!")
                self.__can_trx.send_evt_msg(msg.can_msg)
            else:
                self.logger.debug(
                    f"[{self.__class__}] Modified message {hex(msg_id)} from msg_bundle_list!")
                self.__can_trx.modify_tx_msg(msg.can_msg)
        else:
            self.logger.error(
                f"[{self.__class__}] Message {hex(msg_id)} is not in the CanManager msg_bundle_list!")

    def set_on_can_msg_callback(self, callback):
        self.__external_on_can_msg_callback = callback

    def set_modified_msg_callback(self, callback):
        self.__external_modified_msg_callback = callback

    @property
    def last_msgs(self):
        return self.__can_trx.last_rec_msgs

    @property
    def last_modified_tx_msgs_dict(self):
        return self.__last_modified_tx_msgs_dict

    @property
    def record_last_msgs(self):
        return self.__record_last_msgs

    @property
    def dbc(self):
        return self.__dbc


if __name__ == '__main__':
    import time
    import os
    cwd = os.getcwd()

    dbc_path = os.path.join(cwd, r'res/tesla_can.dbc')
    dbc = cantools.database.load_file(dbc_path)

    init_tx_msgs_path = os.path.join(cwd, r'res/init_tx_msgs.json')
    last_modified_msgs_path = os.path.join(cwd, r'res/last_modified_msgs.json')

    def on_can_msg_callback(msg_id, decoded_data):
        print(f"Receiving {hex(msg_id)}: {decoded_data}")

    def on_can_msg_callback(msg):
        print(f"Receiving {msg}")

    def modified_msg_callback(msg):
        print(f"Modified {msg.arbitration_id}: {msg.data}")

    can_mgr = CanManager(dbc_path=dbc_path,
                         init_tx_msgs_json_path=init_tx_msgs_path,
                         last_modified_tx_msgs_json_path=last_modified_msgs_path,
                         logging_rec_msg=False, record_last_msgs=True)
    can_mgr.set_on_can_msg_callback(on_can_msg_callback)
    can_mgr.set_modified_msg_callback(modified_msg_callback)
    can_mgr.start()
    time.sleep(1)
    print("Modify signals")
    can_mgr.modify_tx_msg(msg_id="0x101", can_data={
                          "GTW_epasTuneRequest": 3, "GTW_epasControlType": 1})
    time.sleep(1)
    can_mgr.stop()
