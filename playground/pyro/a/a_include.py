import os
import sys

def get_workingdir():
    """some shit"""
    print("1:__" + os.path.realpath(__file__))
    print("2:__" + os.path.dirname(sys.argv[0]))
    print("3:__" + os.path.abspath(__file__))
    print("3:__" + os.getcwd())
    print("4:__" + os.path.basename(__file__))
    abspath_argv0 = os.path.abspath(sys.argv[0])
    print("5:__" + abspath_argv0)
    print("6:__" + os.path.dirname(abspath_argv0))  # <====  This is the one! THis should return the path to store PYRO Uri in a textfile

    for a in sys.argv:
        print("\t" + a)