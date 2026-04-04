# Standalone entry point — delegates to atlas.serve
# Move this to atlas-server/ once that package is set up.
from atlas.serve import run

if __name__ == "__main__":
    run()
