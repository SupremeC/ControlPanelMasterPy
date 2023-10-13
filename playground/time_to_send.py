import datetime
from time import sleep

class A:
    _last_sent_hello: datetime.datetime = None
    SEND_HELLO_INTERVALL: int = 2

    def time_to_send_hello(self) -> bool:
        """ Is it time to send hello yet?"""
        return (self._last_sent_hello is None or
                (datetime.datetime.now() - self._last_sent_hello)
                    .total_seconds() > self.SEND_HELLO_INTERVALL)
    
if __name__ == '__main__':
    a = A()
    while(True):
        print(a.time_to_send_hello())
        sleep(.2)
