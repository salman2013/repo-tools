#!/usr/bin/env python
"""
Scrapes and parses information from JIRA's transition states.

Runs the JIRA spider, then parses the output states.json
file to obtain KPI information.

See https://openedx.atlassian.net/wiki/display/OPEN/Tracking+edX+Commitment+To+OSPRs
"""
from __future__ import print_function
from subprocess import check_call

import argparse
import datetime
import dateutil.parser
import json
import sys


EDX_ENGINEERING_STATES = [
    'Needs Triage',
    'Product Review',
    'Community Manager Review',
    'Awaiting Prioritization',
    'Engineering Review',
]


def scrape_jira():
    """
    Re-scrapes jira into states.json
    """
    # Delete content of states.json before re-writing
    with open("states.json", "w"):
        pass

    check_call("scrapy runspider jiraspider.py -o states.json".split(" "))


def engineering_time_spent(state_dict, resolved_date):
    """
    Given a ticket's state dictionary, returns how much engineering time was spent on it.
    Engineering states determined by EDX_ENGINEERING_STATES list.
    """
    # Measurement 1: Average Time Spent by edX Engineering
    # This measurement will sum up the amount of time it takes the engineering team to process OSPR work.
    # AverageTime = sum(amount of time a ticket spends in edX states) / count(all tickets)
    # This will be a rolling average over all tickets currently open, or closed in the past X days.
    # In the initial rollout of this measurement, we'll track for X=14, 30, and 60 days. After we have a few months'
    # worth of data, we can assess what historical interval(s) gives us the most useful, actionable data.
    # This is a measurement across all of engineering.  We are not proposing to measure teams individually.
    total_time = datetime.timedelta(0)
    for state, tdelta in state_dict.iteritems():
        if state in EDX_ENGINEERING_STATES:
            total_time += tdelta

    return total_time


def single_state_time_spent(state_dict, state, resolved_date):
    """
    Given a ticket's state dictionary, returns how much time it spent
    in the given `state`.

    Assumes state_dict has the key `state` present.
    """
    # Measurement 2: Average Time Spent in Scrum Team Backlog
    # For the PRs that need to be reviewed by a scrum team, obtain an average of how long a ticket spends in a team backlog.
    # AverageBacklog = sum(amount of time a ticket spends in "Awaiting Prioritization") /
    #                  count(tickets with a non-zero amount of time spent in "Awaiting Prioritization")
    # This will be a rolling average over all tickets currently open, or closed in the past X days.
    # In the initial rollout of this measurement, we'll track for X=14, 30, and 60 days. After we have a few months'
    # worth of data, we can assess what historical interval(s) gives us the most useful, actionable data.
    return state_dict[state]


def sanitize_ticket_states(state_dict):
    """
    Converts timedelta strings back into timedeltas.
    These were explicitly serialized as '{0.days}:{0.seconds}'.format(tdelta)
    """
    result = {}
    for state, tdelta in state_dict.iteritems():
        tdict = {'days': tdelta[0], 'seconds': tdelta[1]}
        result[state] = datetime.timedelta(**tdict)
    return result


def parse_jira_info(debug=False, pretty=False):
    """
    Read in and parse states.json
    """
    with open("states.json") as state_file:
        # tickets is a list composed of state dictionaries for each ospr ticket.
        # Keys are: 'issue' -> string, 'states' -> dict, 'labels' -> list,
        # Optional keys are: 'resolution' -> list, 'debug' -> string, 'error' -> string
        tickets = json.load(state_file)

    # Set up vars
    triage_time_spent = eng_time_spent = backlog_time = product_time = datetime.timedelta(0)
    num_tickets = backlog_tickets = product_tickets = 0
    # TODO need to get when tickets were merged!
    for ticket in tickets:
        if ticket.get('error', False):
            print("Error in ticket {}: {}".format(ticket['issue'], ticket['error']))
        if debug and ticket.get('debug', False):
            print("Debug: ticket {}: {}".format(ticket['issue'], ticket['debug']))

        if ticket.get('resolved', False):
            # Turn str(datetime) back into a datetime object
            ticket['resolved'] = dateutil.parser.parse(ticket['resolved'])
        else:
            # Ticket is not yet resolved. Set "resolved" date to right now, so it'll
            # show up in the filter for being resolved within the past X days (hack for cleaner code)
            ticket['resolved'] = datetime.datetime.now()

        if ticket.get('states', False):
            # Sanitize ticket state dict (need to convert time strings to timedeltas)
            ticket['states'] = sanitize_ticket_states(ticket['states'])

            # Get amount of time this spent in "Needs Triage" (roughly, time to first response)
            triage_time_spent += single_state_time_spent(ticket['states'], 'Needs Triage', ticket['resolved'])

            # Calculate total time spent by engineering team on this ticket
            eng_time_spent = engineering_time_spent(ticket['states'], ticket['resolved'])
            num_tickets += 1

            # Get time spent in backlog
            if ticket['states'].get('Awaiting Prioritization', False):
                backlog_time += single_state_time_spent(ticket['states'], 'Awaiting Prioritization', ticket['resolved'])
                backlog_tickets += 1

            # Get time spent in product review
            if ticket['states'].get('Product Review', False):
                product_time += single_state_time_spent(ticket['states'], 'Product Review', ticket['resolved'])
                product_tickets += 1

        elif debug or pretty:
            print("No states yet for newly-opened ticket {}".format(ticket['issue']))

    print_time_spent(triage_time_spent, num_tickets, 'Average time spent in Needs Triage', pretty)
    print_time_spent(eng_time_spent, num_tickets, 'Average time spent in edX engineering states', pretty)
    print_time_spent(backlog_time, backlog_tickets, 'Average time spent in team backlog', pretty)
    print_time_spent(product_time, product_tickets, 'Average time spent in product review', pretty)


def print_time_spent(time_spent, ticket_count, message, pretty):
    """
    Prints out the average time spent over the number of tickets.
    Message should be the header message to print out.
    """
    # Calculate average engineering time spent
    avg_time = time_spent / ticket_count
    # Pretty print the average time
    days = avg_time.days
    hours, remainder = divmod(avg_time.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    print('\n' + message + ', over {} tickets'.format(ticket_count))
    if pretty:
        print('\t {} days, {} hours, {} minutes, {} seconds'.format(days, hours, minutes, seconds))
    else:
        print('\t {}:{}:{}:{}'.format(days, hours, minutes, seconds))


def main(argv):
    """a docstring for main, really?"""
    parser = argparse.ArgumentParser(description="Summarize JIRA info.")
    parser.add_argument(
        "--no-scrape", action="store_true",
        help="Don't re-run the scraper, just read the current states.json file"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Show debugging messages"
    )
    parser.add_argument(
        "--pretty", action="store_true",
        help="Pretty print output"
    )
    args = parser.parse_args(argv[1:])

    if not args.no_scrape:
        scrape_jira()

    parse_jira_info(args.debug, args.pretty)

if __name__ == "__main__":
    sys.exit(main(sys.argv))
