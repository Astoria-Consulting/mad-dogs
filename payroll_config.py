# Payroll Calculator Configuration

# Date Range for Payroll Calculation
year = "2021"
month = "08"
start_day = "16"
end_day = "31"

# roles = ["Server", "Kitchen", "Bartender", "Host"]

# Tipouts go to these roles
tipouts_to_role = {"Beverage": [""],
                   "Liquor": ["Bartender"],
                   "Beer": ["Bartender"],
                   "Wine": ["Bartender"],
                   "Dogs": ["Kitchen"],
                   "Bites": ["Kitchen"],
                   "Dessert": ["Kitchen"],
                   "Merchandise": [""],
                   "Salad": ["Kitchen"],
                   "Kids Meal/Sides/Salad": ["Kitchen"],
                   "Cocktails": ["Bartender"],
                   "Brunch": ["Kitchen"],
                   "Mora": [""]}

# Tipouts are taken from these roles
tipouts_from_role = {"Beverage": [""],
                     "Liquor": ["Server"],
                     "Beer": ["Server"],
                     "Wine": ["Server"],
                     "Dogs": ["Server", "Bartender"],
                     "Bites": ["Server", "Bartender"],
                     "Dessert": ["Server", "Bartender"],
                     "Merchandise": [""],
                     "Salad": ["Server", "Bartender"],
                     "Kids Meal/Sides/Salad": ["Server", "Bartender"],
                     "Cocktails": ["Server"],
                     "Brunch": ["Server", "Bartender"],
                     "Mora": [""]}

# These are the percentages used to calculate tipouts
BARTENDER_PERCENTAGE = .05
KITCHEN_PERCENTAGE = .03
