import time
from Pyro5.api import Proxy
import a.a_include

a.a_include.get_workingdir()
exit()

print("First make sure one of the gui servers is running.")
print("Enter the object uri that was printed:")
uri = input().strip()
guiserver = Proxy(uri)

guiserver.message("Hello there!")
time.sleep(0.5)
guiserver.message("How's it going?")
time.sleep(1)

for i in range(20):
    guiserver.message(f"Counting {0}".format(i))

server_answer = guiserver.say_hello()
print("server said--> " + str(server_answer))

guiserver.message("now calling the sleep method with 5 seconds")
guiserver.sleep(10)
guiserver.message("How's it going?")
guiserver.stoopp()
print("client stopped")
