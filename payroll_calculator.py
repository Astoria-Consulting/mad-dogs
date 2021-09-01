import functools
import os
import time
import payroll_config

from dateutil import parser
import datetime
import concurrent.futures

from square.client import Client
import pytz

est = pytz.timezone('US/Eastern')
year = payroll_config.year
month = payroll_config.month
start_day = payroll_config.start_day
if len(start_day) == 1:
    start_day = f"0{start_day}"
end_day = payroll_config.end_day
if len(end_day) == 1:
    start_day = f"0{end_day}"
tipouts_to_role = payroll_config.tipouts_to_role
tipouts_from_role = payroll_config.tipouts_from_role
BARTENDER_PERCENTAGE = payroll_config.BARTENDER_PERCENTAGE
KITCHEN_PERCENTAGE = payroll_config.KITCHEN_PERCENTAGE

access_token = os.getenv("SQUARE_ACCESS_TOKEN")

client = Client(
    square_version='2021-07-21',
    access_token=access_token,
    environment='production',
    custom_url='https://connect.squareup.com', )


def log(message):
    message_timestamp = datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d_%H.%M.%S')
    full_message = f"{message_timestamp} {message}"
    print(full_message, flush=True)


def get_active_team_members():
    team_result = client.team.search_team_members(body={})
    team_members = team_result.body["team_members"]
    member_id_to_name = {}
    member_id_to_created_at = {}
    for team_member in team_members:
        member_id_to_name[team_member["id"]] = f"{team_member['family_name']}, {team_member['given_name']}"
        member_id_to_created_at[team_member["id"]] = team_member["created_at"]

    return member_id_to_created_at, member_id_to_name


def get_categories():
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

    return category_id_to_name


def get_shifts(begin_time, end_time):
    cursor = ""
    all_shifts = []
    while True:
        if cursor:
            shift_result = client.labor.search_shifts(
                body={
                    "cursor": cursor,
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
        else:
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
        if shift_result.is_success():
            if shift_result.body:
                current_shifts = shift_result.body["shifts"]
                all_shifts += current_shifts
                cursor = shift_result.body.get('cursor', None)
            else:
                log("No shifts")
                break
        elif shift_result.is_error():
            log(f"Errors: {shift_result.errors}")
            break

        if cursor is None:
            break

    return all_shifts


def get_workers(current_timestamp, current_roles, shifts, member_id_to_created_at):
    worker_matches = []
    for current_shift in shifts:
        # Ensure Role Match
        if current_shift["wage"]["title"] in current_roles:
            # Ensure Time Match
            if current_shift["start_at"] <= current_timestamp <= current_shift["end_at"]:
                # Ensure that, if kitchen shift, team member started more than 31 days ago.
                # if current_shift["wage"]["title"] == "Kitchen":
                #     member_start_date = parser.parse(member_id_to_created_at[current_shift["team_member_id"]])
                #     current_timestamp = datetime.datetime.now()
                #     delta = datetime.timedelta(days=31)
                #     if current_timestamp < member_start_date + delta:
                #         # This kitchen worker started more recently than 31 days ago. Skip them
                #         continue

                worker_matches.append(current_shift["team_member_id"])

    return worker_matches


def process_line_item(line_item, order_timestamp, category_id_to_name, workers_net_tips, shifts,
                      member_id_to_created_at, cashier, member_id_to_name):
    dollar_amount = line_item["gross_sales_money"]["amount"]

    if "catalog_object_id" not in line_item:
        return
    catalog_object_id = line_item["catalog_object_id"]
    catalog_object = client.catalog.retrieve_catalog_object(
        object_id=catalog_object_id
    )
    if catalog_object.status_code > 300:
        for error in catalog_object.errors:
            log(f"Error: {error['detail']}")

        return

    item_id = catalog_object.body["object"]["item_variation_data"]["item_id"]
    item = client.catalog.retrieve_catalog_object(
        object_id=item_id
    )
    category_id = item.body["object"]["item_data"]["category_id"]
    category_name = category_id_to_name[category_id]
    to_roles = tipouts_to_role[category_name]

    to_workers = get_workers(order_timestamp, to_roles, shifts, member_id_to_created_at)
    if len(to_workers) == 0:
        return

    # calculate percentage for current item
    if to_roles[0] == "Kitchen":
        percentage = KITCHEN_PERCENTAGE
    elif to_roles[0] == "Bartender":
        percentage = BARTENDER_PERCENTAGE
    else:
        percentage = 0

    tipout_total = dollar_amount * percentage

    workers_net_tips[cashier] -= tipout_total

    to_each = tipout_total / len(to_workers)
    for to_worker in to_workers:
        log(f"Giving {to_each/100} to {member_id_to_name[to_worker]}")
        workers_net_tips[to_worker] += to_each


def process_payment(payment, processed_orders, workers_net_tips, category_id_to_name, shifts, member_id_to_created_at,
                    member_id_to_name):
    # Add the credit card tips to the worker who rang the order (cashier)
    cashier = payment["employee_id"]

    cc_tips = 0
    if "tip_money" in payment:
        cc_tips = payment["tip_money"]["amount"]
        if cashier in workers_net_tips:
            workers_net_tips[cashier] += cc_tips
        else:
            workers_net_tips[cashier] = cc_tips

    # get order
    order_result = client.orders.retrieve_order(
        order_id=payment["order_id"]
    )
    if "order" not in order_result.body:
        return
    order = order_result.body['order']
    order_id = order['id']
    if order_id in processed_orders:
        log(f"Already processed order {order_id}. Skipping")
        return
    else:
        processed_orders[order_id] = None

    order_datetime = parser.parse(order["created_at"])
    order_timestamp = order_datetime.astimezone(est).strftime('%Y-%m-%dT%H:%M:%SZ')
    log(f"Order {order_id}. Cashier: {member_id_to_name[cashier]}. Tips: {cc_tips/100}. Time: {order_timestamp}")

    if "line_items" not in order:
        return
    line_items = order['line_items']
    for line_item in line_items:
        process_line_item(line_item, order_timestamp, category_id_to_name, workers_net_tips, shifts,
                          member_id_to_created_at, cashier, member_id_to_name)


def get_all_payments(begin_time, end_time):
    cursor = ""
    all_payments = []
    while True:
        if cursor:
            payments_result = client.payments.list_payments(
                cursor=cursor,
                begin_time=begin_time,
                end_time=end_time
            )
        else:
            payments_result = client.payments.list_payments(
                begin_time=begin_time,
                end_time=end_time
            )
        if payments_result.is_success():
            if payments_result.body:
                current_payments = payments_result.body['payments']
                all_payments += current_payments
                cursor = payments_result.body.get('cursor', None)
            else:
                log("No payments")
                break
        elif payments_result.is_error():
            log(f"Errors: {payments_result.errors}")
            break

        if cursor is None:
            break

    return all_payments


def get_hours_billed(shifts):
    hours_billed = {}

    for shift in shifts:
        member = shift["team_member_id"]
        title = shift["wage"]["title"]

        start_time = parser.parse(shift["start_at"])
        end_time = parser.parse(shift["end_at"])
        shift_time = end_time - start_time
        if "breaks" in shift:
            for shift_break in shift["breaks"]:
                break_start_time = parser.parse(shift_break["start_at"])
                break_end_time = parser.parse(shift_break["end_at"])
                break_time = break_end_time - break_start_time
                shift_time -= break_time

        if member in hours_billed:
            hours_billed[member][title] += shift_time
        else:
            hours_billed[member] = {"Kitchen": datetime.timedelta(),
                                    "Bartender": datetime.timedelta(),
                                    "Server": datetime.timedelta(),
                                    "Host": datetime.timedelta()}
            hours_billed[member][title] = shift_time

    return hours_billed


def format_timedelta(timedelta):
    days = timedelta.days
    hours, rem = divmod(timedelta.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    hours += days * 24
    return f"{hours}:{minutes}:{seconds}"


def main():
    start_date = f"{year}-{month}-{start_day}"
    end_date = f"{year}-{month}-{end_day}"
    log(f"Processing Payroll from {start_date} to {end_date}")

    member_id_to_created_at, member_id_to_name = get_active_team_members()
    category_id_to_name = get_categories()

    begin_time = f"{start_date}T00:00:00.000Z"
    end_time = f"{end_date}T23:59:59.999Z"

    shifts = get_shifts(begin_time, end_time)
    hours_billed = get_hours_billed(shifts)

    workers_net_tips = {}
    for shift in shifts:
        workers_net_tips[shift["employee_id"]] = 0

    log("Getting all payments in the pay period")
    all_payments = get_all_payments(begin_time, end_time)
    log(f"Number of Payments: {len(all_payments)}")

    processed_orders = {}
    process_payment_threaded = functools.partial(process_payment,
                                                 processed_orders=processed_orders,
                                                 workers_net_tips=workers_net_tips,
                                                 category_id_to_name=category_id_to_name,
                                                 shifts=shifts,
                                                 member_id_to_created_at=member_id_to_created_at,
                                                 member_id_to_name=member_id_to_name)
    with concurrent.futures.ThreadPoolExecutor(max_workers=None) as executor:
        executor.map(process_payment_threaded, all_payments)

    log("Processing for pay period complete. Results:")
    print("Member Name|Net Tips|Kitchen Hours|Bartender Hours|Server Hours|Host Hours")
    for worker in workers_net_tips:
        net_tips = "{:.2f}".format(workers_net_tips[worker]/100)
        print(f"{member_id_to_name[worker]}|{net_tips}|"
              f"{format_timedelta(hours_billed[worker]['Kitchen'])}|"
              f"{format_timedelta(hours_billed[worker]['Bartender'])}|"
              f"{format_timedelta(hours_billed[worker]['Server'])}|"
              f"{format_timedelta(hours_billed[worker]['Host'])}")


if __name__ == '__main__':
    main()
