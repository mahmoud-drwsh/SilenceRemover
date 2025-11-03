Param(
    [string]$InputDir = "/Users/mahmoud/Desktop/VIDS",
    [int]$Target = 150
)

uv run python main.py run-all -i $InputDir -t $Target


