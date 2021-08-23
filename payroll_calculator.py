from square.client import Client

# TIP CALCULATOR
start_date = "2021-08-11"
end_date = "2021-08-12"
print(f"Processing Payroll from {start_date} to {end_date}")

# roles = ["Server", "Kitchen", "Bartender"]
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

BARTENDER_PERCENTAGE = .05
KITCHEN_PERCENTAGE = .03

client = Client(
    square_version='2021-07-21',
    access_token='EAAAFG9dhJNnbJo1gEdqny15pph2vrFekCxqqEfzcAGsKyXTCFPAMyGOfZoWpH2q',
    environment='production',
    custom_url='https://connect.squareup.com', )
begin_time = f"{start_date}T00:00:00.000Z"
# end_time = f"{end_date}T23:59:59.999Z"
end_time = f"{end_date}T00:00:00.000Z"

# # Build data in memory # #
# Get locations
location_result = client.locations.list_locations()
location_id = location_result.body["locations"][0]["id"]

# Get active team members
team_result = client.team.search_team_members(body={})
team_members = team_result.body["team_members"]
member_id_to_name = {}
for team_member in team_members:
    # if kitchen worked less than a month, no tips
    member_id_to_name[team_member["id"]] = f"{team_member['given_name']} {team_member['family_name']}"

# Get shifts for time range
shift_result = client.labor.search_shifts(
  body={
    "query": {
      "filter": {
        "location_ids": [],
        "start": {
          "start_at": begin_time,
          "end_at": end_time
        },
        "team_member_ids": [
          None
        ]
      }
    }
  }
)
shifts = shift_result.body["shifts"]

# Get workers
workers_net_tips = {}
for shift in shifts:
    workers_net_tips[shift["employee_id"]] = 0

# Get categories
category_result = client.catalog.search_catalog_objects(
    body={
        "object_types": [
            "CATEGORY"
        ]
    }
)
categories = category_result.body["objects"]
category_id_to_name = {}
for category in categories:
    category_id_to_name[category['id']] = category["category_data"]["name"]


def get_workers(current_timestamp, current_roles):
    worker_matches = []
    for current_shift in shifts:
        # Ensure Role Match
        if current_shift["wage"]["title"] in current_roles:
            # Ensure Time Match
            if current_shift["start_at"] <= current_timestamp <= current_shift["end_at"]:
                worker_matches.append(current_shift["team_member_id"])

    return worker_matches


# get payments for today
payments = client.payments.list_payments(
    begin_time=begin_time,
    end_time=end_time
)
processed_orders = {}
print(f"Payments: {len(payments.body['payments'])}")
for count, payment in enumerate(payments.body["payments"], start=1):
    # Add the credit card tips to the worker who rang the order
    if "tip_money" in payment:
        cc_tips = payment["tip_money"]["amount"]
        if payment["employee_id"] in workers_net_tips:
            workers_net_tips[payment["employee_id"]] += cc_tips
        else:
            print(f"{member_id_to_name[payment['employee_id']]} did not clock in.")

    # get order
    order_result = client.orders.retrieve_order(
        order_id=payment["order_id"]
    )
    if "order" not in order_result.body:
        continue
    order = order_result.body['order']
    order_id = order['id']
    if order_id in processed_orders:
        print(f"Already processed order {order_id}. Skipping")
        continue
    else:
        processed_orders[order_id] = None
    print(f"Order {count}: {order_id}")
    order_timestamp = order["created_at"]

    if "line_items" not in order:
        continue
    line_items = order['line_items']
    for line_item in line_items:
        dollar_amount = line_item["gross_sales_money"]["amount"]

        if "catalog_object_id" not in line_item:
            continue
        catalog_object_id = line_item["catalog_object_id"]
        catalog_object = client.catalog.retrieve_catalog_object(
            object_id=catalog_object_id
        )
        item_id = catalog_object.body["object"]["item_variation_data"]["item_id"]
        item = client.catalog.retrieve_catalog_object(
            object_id=item_id
        )
        category_id = item.body["object"]["item_data"]["category_id"]
        category_name = category_id_to_name[category_id]
        from_roles = tipouts_from_role[category_name]
        to_roles = tipouts_to_role[category_name]

        # determine the from workers for that category
        from_workers = get_workers(order_timestamp, from_roles)
        to_workers = get_workers(order_timestamp, to_roles)
        if len(from_workers) == 0 or len(to_workers) == 0:
            continue
        # calculate percentage for current item
        if to_roles[0] == "Kitchen":
            percentage = KITCHEN_PERCENTAGE
        elif to_roles[0] == "Bartender":
            percentage = BARTENDER_PERCENTAGE
        else:
            percentage = 0

        tipout_total = dollar_amount * percentage

        from_each = tipout_total / len(from_workers)
        for from_worker in from_workers:
            workers_net_tips[from_worker] -= from_each

        to_each = tipout_total / len(to_workers)
        for to_worker in to_workers:
            workers_net_tips[to_worker] += to_each


for worker in workers_net_tips:
    print(f"{member_id_to_name[worker]} | {workers_net_tips[worker]}")
