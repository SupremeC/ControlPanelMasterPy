from enum import IntEnum


class EffectType (IntEnum):
    NONE_ = 0,
    REVERB = 1
    PHASER = 2
    REVERSE = 3
    XXX = 4
    PITCHLOWER = 5
    PITCHHIGHER = 6
    TIMECOMPRESS = 7
    TIMESTRETCH = 8



class AudioEffect:
    def do_effect(self, infile: str, effect: EffectType) -> str:
        if effect == EffectType.NONE_:
            return infile
        if effect == EffectType.REVERB:
            return AudioEffect.reverb()
        pass

    def reverb(infile: str, effect: EffectType) -> str:
        pass