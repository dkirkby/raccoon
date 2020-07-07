"""Definition of the CAN frames used by DESI for high-level analysis.
"""
desi_commands = {
    2: 'set_currents',
    3: 'set_periods',
    4: 'set_up_move',
    5: 'set_reset_leds',
    6: 'run_test_sequence',
    7: 'execute_move_table',
    8: 'get_move_table_status',
    9: 'get_temperature',
    10: 'get_CAN_address',
    11: 'get_firmware_version',
    12: 'get_device_type',
    13: 'get_movement_status',
    14: 'get_current_monitor_vals',
    15: 'get_bootloader_version',
    16: 'set_duty_fid',
    17: 'read_sid_lower',
    18: 'read_sid_upper',
    19: 'read_sid_short',
    20: 'write_CAN_address',
    21: 'read_CAN_address',
    22: 'check_sid_lower',
    23: 'check_sid_upper',
    24: 'check_sid_short',
    25: 'check_device',
    30: 'set_currents_legacy',
    31: 'set_motor_parameters_legacy',
    32: 'set_cruise_and_cw_creep_amounts_legacy',
    33: 'set_up_move_legacy',
    34: 'execute_move_legacy',
    35: 'flash_leds_legacy',
    36: 'get_bootloader_version_alt',
    37: 'get_firmware_version_alt',
    40: 'enter_stop_mode, exit via SYNC',
    41: 'enter_stop_mode, exit via CAN',
    43: 'enter_bootloader_mode',
    44: 'dump_n_bytes',
    45: 'get_fw_flash_checksum',
    46: 'get_sync_status',
    47: 'get_system_clock',
    48: 'set_fid_pwm_frequency',
    49: 'get_fid_pwm_frequency',
}

class DESIcanbus(object):

    def __init__(self):
        self.last_command_id = None

    def __call__(self, frame):
        """Implement the session high-level analysis (HLA) API.
        """
        response = bool(frame['ID'] & 0x10000000)
        if response:
            positioner_id = frame['ID'] & 0xfffff
            if self.last_command_id == 9:
                temperature = (frame['DATA'][1] << 8) | frame['DATA'][0]
                return f'{positioner_id:d} T={temperature:04X}'
            else:
                return f'<={positioner_id:d}'
        else:
            command_id = frame['ID'] & 0xff
            if command_id not in desi_commands:
                return None
            command_name = desi_commands[command_id]
            positioner_id = frame['ID'] >> 8
            if positioner_id == 20000:
                positioner_name = 'ALL'
            elif positioner_id == 20001:
                positioner_name= 'ALLPOS'
            elif positioner_id == 20002:
                positioner_name = 'ALLFID'
            else:
                positioner_name = f'{positioner_id:d}'
            self.last_command_id = command_id
            return f'{command_name}=>{positioner_name}'
