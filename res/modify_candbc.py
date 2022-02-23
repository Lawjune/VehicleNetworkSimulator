import cantools
import os
cwd = os.getcwd()

dbc_path = os.path.join(cwd, r'res/tesla_can.dbc')
dbc = cantools.database.load_file(dbc_path)

msg = dbc.get_message_by_frame_id(0x488)
print(msg)
