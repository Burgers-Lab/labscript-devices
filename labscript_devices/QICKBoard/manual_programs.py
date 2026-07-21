"""Small built-in tProc v1 programs for QICKBoard's BLACS manual-control panel.

These run on demand from the BLACS tab (see blacs_tabs.py's "Manual Program
Control" group and blacs_workers.py's run_manual_program()), independent of
any labscript shot -- meant for quick hardware bring-up/debugging, not for use
in an actual experiment sequence.
"""
from qick import AveragerProgram

# Sentinel meaning "run whatever tproc_program_module/class/kwargs the
# connection table configured" rather than one of the MANUAL_PROGRAMS entries
# below -- shared between blacs_tabs.py (the combo box) and blacs_workers.py
# (run_manual_program()).
CONNECTION_TABLE_PROGRAM = "__connection_table_program__"


class ContinuousTone(AveragerProgram):
    """Outputs one constant tone that repeats forever in hardware.

    Uses the DAC's periodic mode (style="const", mode="periodic") rather than
    a software loop -- tProc v1 has no unconditional-jump instruction, only
    conditional loopnz/condj, so an indefinite output is done by asking the
    generator itself to repeat the waveform after a single pulse() call, the
    same mechanism amo_qick's own QickSoc.reset_gens()/demo notebooks use.
    Keeps repeating until stop_manual_program() (soc.reset_gens()) is called.
    """

    def initialize(self):
        cfg = self.cfg
        res_ch = cfg["res_ch"]

        self.declare_gen(ch=res_ch, nqz=1)
        freq = self.freq2reg(cfg["pulse_freq"], gen_ch=res_ch)
        phase = self.deg2reg(cfg.get("res_phase", 0), gen_ch=res_ch)
        length = self.us2cycles(cfg["pulse_length_us"], gen_ch=res_ch)
        self.set_pulse_registers(
            ch=res_ch, style="const", mode="periodic", freq=freq, phase=phase,
            gain=cfg["pulse_gain"], length=length,
        )

        self.synci(200)

    def body(self):
        # Arms the periodic tone -- the DAC keeps outputting after this single
        # call, so no wait_all() here (there's no fixed-length pulse to wait on).
        self.pulse(ch=self.cfg["res_ch"])


CONTINUOUS_TONE_CONFIG = {
    "res_ch": 0,
    "pulse_freq": 110,        # MHz
    "pulse_gain": 3000,
    "pulse_length_us": 1.0,   # microseconds -- one period of the repeated waveform
    "res_phase": 0,
    "reps": 1,
}
import numpy as np
class InterleavedTone(AveragerProgram):

    """Outputs one constant tone that repeats forever in hardware.

    Uses the DAC's periodic mode (style="const", mode="periodic") rather than
    a software loop -- tProc v1 has no unconditional-jump instruction, only
    conditional loopnz/condj, so an indefinite output is done by asking the
    generator itself to repeat the waveform after a single pulse() call, the
    same mechanism amo_qick's own QickSoc.reset_gens()/demo notebooks use.
    Keeps repeating until stop_manual_program() (soc.reset_gens()) is called.
    """

    def initialize(self):
        cfg = self.cfg
        
        duty_time_us = cfg["pulse_length_us"]/len(cfg["channels"])
        samples_per_clock = self.soccfg["gens"]["res_ch"]["samples_per_clock"]
        for i, res_ch in enumerate(cfg["channels"]):

            #calculate the waveform as a square pulse with an on cycle determined by the period of the overall pulse:
            first_off = samples_per_clock * i * self.us2cycles(duty_time_us)
            on = samples_per_clock * self.us2cycles(duty_time_us)
            last_off = self.us2cycles(duty_time_us) - first_off -on
            wave = self.np.concatenate(np.zeros(first_off), np.full(on, cfg["pulse_gain"]), np.zeros(last_off))
            self.declare_gen(ch=res_ch, nqz=1)
            freq = self.freq2reg(cfg["pulse_freq"], gen_ch=res_ch)
            phase = self.deg2reg(cfg.get("res_phase", 0), gen_ch=res_ch)
            length = self.us2cycles(cfg["pulse_length_us"], gen_ch=res_ch)
            self.set_pulse_registers(
                ch=res_ch, style="arb", mode="periodic", freq=freq, phase=phase,
                gain=cfg["pulse_gain"], waveform=wave, 
            )

        self.synci(200)

    def body(self):
        # Arms the periodic tone -- the DAC keeps outputting after this single
        # call, so no wait_all() here (there's no fixed-length pulse to wait on).
        self.pulse(ch=self.cfg["channels"])

INTERLEAVED_TONE_CONFIG = {
    "channels": [0,1,2], # Number of channels for tproc1 ZCU starts at 8 and goes to 14 but in tproc1 that reg 0-6
    "pulse_freq": 110,        # MHz
    "pulse_gain": 3000,
    "pulse_length_us": 1.0,   # microseconds -- one period of the repeated waveform
    "res_phase": 0,
    "reps": 1,
}
MANUAL_PROGRAMS = {
    "110 MHz continuous": (ContinuousTone, CONTINUOUS_TONE_CONFIG),
    "110 MHz Interleaved": (InterleavedTone, INTERLEAVED_TONE_CONFIG),
}
