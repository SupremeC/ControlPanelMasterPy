from time import time, sleep


class SlidingWindow:
    '''
    Rate throttling. Determnes how many packages are allowed per timeUnit.

    :param limit_per_timeunit: How many packages are allowed to be sent per timeunit
    :param time_unit: Length of time_unit
    '''
    limit_per_timeunit: int
    time_unit: float = 0


    #def __init__(self, capacity, time_unit, forward_callback, drop_callback):
    def __init__(self, limit_per_timeunit: int, time_unit: float):
        self.limit_per_timeunit: int = limit_per_timeunit
        self.time_unit: float = time_unit
        self._cur_time = time()
        self._pre_count: int = limit_per_timeunit
        self._cur_count: int = 0

    def ok_to_send(self):
        '''Check if can accept this request without exceding rate limit'''
        if (time() - self._cur_time) > self.time_unit:
            self._cur_time = time()
            self._pre_count = self._cur_count
            self._cur_count = 0

        ec = (self._pre_count * (self.time_unit - (time() - self._cur_time)) / self.time_unit) + self._cur_count

        if (ec > self.limit_per_timeunit):
            return False

        self._cur_count += 1
        return True