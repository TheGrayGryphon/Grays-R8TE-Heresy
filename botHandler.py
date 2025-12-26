import asyncio
import threading
from collections import defaultdict
import discord  # noqa This libray is covered in py-cord
from discord.ext import tasks  # noqa This libray is covered in py-cord
from discord import option  # noqa This libray is covered in py-cord
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import glob
import os
from typing import Union
from r8teInclude import (WORLDSAVE_PATH, AEI_PATH, LOG_FILENAME, AI_ALERT_TIME, PLAYER_ALERT_TIME, PLAYER_DB_FILENAME,
                         JOB_DB_FILENAME, REMINDER_TIME, BOT_TOKEN, CH_LOG, CH_ALERT, CH_DETECTOR, CREWED_TAG,
                         COMPLETED_TAG, AVAILABLE_TAG, STAFF_TAG, LOCATION_DB, SCAN_TIME, IGNORED_TAGS, REBOOT_TIME,
                         PLAYER_RESPAWN_TIME, RED_SQUARE, RED_EXCLAMATION, GREEN_CIRCLE, AXE, TRACK_AI_DD,
                         JOB_TRACK_FORUM, JOB_POST_FORUM, STATUS_REPORT_TIME, VERSION)

from r8teInclude import Car, Cut, Train, Player, AeiReport, CarReport, Job, DeletedTrainWatch
import shutil

DEBUG = True

# Necessary Bot intents
intents = discord.Intents.default()
intents.guilds = True  # noqa
intents.messages = True  # noqa
intents.message_content = True  # noqa

SAVENAME = WORLDSAVE_PATH + '/Auto Save World.xml'
DIESEL_ENGINE = 'US_DieselEngine'
DISCORD_CHAR_LIMIT = 2000
DISTANCE_JITTER = 1.0  # Difference value used to determine if a train is moving
TMP_FILENAME = 'r8te_msg.txt'

event_db = list()

curr_trains = dict()  # Dict of all trains in the world
watched_trains = dict()  # Dict of trains which are stalled/stuck
players = dict()  # Dict of player controlled trains
alert_messages = defaultdict(list)  # Dict of messages sent to alert channel
detector_reports = defaultdict(list)
deleted_player_trains = defaultdict(DeletedTrainWatch)
working_jobs = dict()
detector_files = list()
detector_file_time: float = 0.0

global last_world_datetime


def parse_train_loader(root):
    cuts = list()
    for t in root.iter('TrainLoader'):
        train_id = t.find('trainID').text
        was_ai = t.find('TrainWasAI').text
        direction = t.find('DispatchTrainDirection').text
        speed_limit = t.find('ManuallyAppliedSpeedLimitMPH').text
        prev_signal = t.find('PreviousSignalInstruction').text
        units = list()
        unit_loader = t.find('unitLoaderList')
        for rail_vehicle in unit_loader.iter('RailVehicleStateClass'):
            file_name = rail_vehicle.find('rvXMLfilename').text
            unit_type = rail_vehicle.find('unitType').text
            route_prefix_1 = rail_vehicle.find('currentRoutePrefix')[0].text
            track_index_1 = rail_vehicle.find('currentTrackSectionIndex')[0].text
            start_node_1 = rail_vehicle.find('startNodeIndex')[0].text
            distance_1 = rail_vehicle.find('distanceTravelledInMeters')[0].text
            reverse_1 = rail_vehicle.find('reverseDirection')[0].text
            if len(rail_vehicle.find("currentRoutePrefix")) > 1:
                route_prefix_2 = rail_vehicle.find('currentRoutePrefix')[1].text
                track_index_2 = rail_vehicle.find('currentTrackSectionIndex')[1].text
                start_node_2 = rail_vehicle.find('startNodeIndex')[1].text
                distance_2 = rail_vehicle.find('distanceTravelledInMeters')[1].text
                reverse_2 = rail_vehicle.find('reverseDirection')[1].text
            else:
                route_prefix_2 = None
                track_index_2 = None
                start_node_2 = None
                distance_2 = None
                reverse_2 = None
            load_weight = rail_vehicle.find('loadWeightUSTons').text
            dest_tag = rail_vehicle.find('destinationTag').text
            unit_number = rail_vehicle.find('unitNumber').text
            hazmat_tag = rail_vehicle.find('hazmatPlacardIndex').text
            units.append(
                Car(file_name, unit_type, route_prefix_1, route_prefix_2, track_index_1, track_index_2, start_node_1,
                    start_node_2, distance_1, distance_2, reverse_1, reverse_2, load_weight, dest_tag, unit_number,
                    hazmat_tag))
        cuts.append(Cut(train_id, was_ai, direction, speed_limit, prev_signal, units.copy()))
        units.clear()
    return cuts


def location(route_id, track_index):
    sub = int(route_id)
    trk = int(track_index)

    if sub in LOCATION_DB:
        try:
            return LOCATION_DB[sub]
        except KeyError:
            return route_id
    else:
        return route_id


def locos_in_cut(cars):     # Return a list of all locomotives within this cut of cars
    locos = list()
    for i in range(len(cars.consist)):
        if cars.consist[i].unit_type == DIESEL_ENGINE:
            locos.append(i)
    return locos


def update_world_state(last_update_time, world_trains):
    msg = None
    try:
        tree = ET.parse(SAVENAME)
        root = tree.getroot()
    except ET.ParseError as e:
        msg = f'ET.ParseError: {e} encountered while parsing {SAVENAME}, returning last world state and '
        msg += 'copying world save to file:"CORRUPT_WORLD_SAVE.xml'
        shutil.copy(f'{SAVENAME}', WORLDSAVE_PATH + '/CORRUPT_WORLD_SAVE.xml')
        return last_update_time, msg

    world_trains.clear()
    world_save_datetime = datetime.strptime(root.find('date').text.split('.')[0], '%Y-%m-%dT%H:%M:%S')
    cuts = parse_train_loader(root)
    # Walk through each cut of cars and save only those with locomotives in them
    for cut in cuts:
        try:
            if locos_in_cut(cut):
                tid = cut.train_id
                nbr = cut.consist[0].unit_number
                rp_1 = cut.consist[0].route_1
                rp_2 = cut.consist[0].route_2
                ts_1 = cut.consist[0].track_1
                ts_2 = cut.consist[0].track_2
                dist_1 = cut.consist[0].dist_1
                dist_2 = cut.consist[0].dist_2
                eng = 'None'
                tag = 'NON_LEADER_LOCO'
                train_type = 'Cut'
                if cut.consist[0].unit_type == DIESEL_ENGINE:  # Lead loco - grab the symbol
                    tag = cut.consist[0].dest_tag
                    if 'amtrak' in cut.consist[0].filename.lower():
                        train_type = 'Passenger'
                    else:
                        train_type = 'Freight'
                    if cut.is_ai is True:
                        eng = 'AI'
                world_trains[tid] = Train(tid, tag, nbr, train_type, len(cut.consist), eng, cut.consist.copy(),
                                          world_save_datetime, rp_1, rp_2, ts_1, ts_2, dist_1, dist_2)
            else:
                # No locomotives found in cut, so not tracking it
                pass

        except IndexError:
            msg = (f'**WARNING** : Malformed train found in WorldSave.xml. Likely a server reboot is in order.'
                   f' TID = {cut.train_id}')

    return world_save_datetime, msg


def find_tid_by_symbol(train_tag, train_list):
    for tid in train_list:
        if train_list[tid].symbol.lower() == train_tag.lower():
            return tid
    return -1


def find_tid_by_loco_num(loco_num, train_list):
    for tid in train_list:
        if train_list[tid].symbol.lower() == loco_num.lower():
            return tid
    return -1


def find_symbol_in_consist(train_tag, train_list):
    '''
    :param train_tag: Railvehicle tag/symbol to search for
    :param train_list: List of trains to search
    :return: Tuple of which train id the tag was found in and its location in the consist, or None if not found
    '''
    for tid in train_list:
        i = 0
        for rail_vehicle in train_list[tid].consist:
            if rail_vehicle.dest_tag.lower() == train_tag.lower():
                return tid, i
            i += 1
    return None


def train_count(train_type, world_trains, watched_trains):
    count = 0
    if train_type.lower() == 'ai':  # Trains crewed by AI
        for tid in world_trains:
            if world_trains[tid].engineer.lower() == 'ai':
                count += 1
    elif train_type.lower() == 'player':  # Trains crewed by players
        for tid in world_trains:
            if (world_trains[tid].engineer.lower() != 'none' and world_trains[tid].engineer.lower() != 'ai' and
                    world_trains[tid].symbol != 'NON_LEADER_LOCO'):
                count += 1
    elif train_type.lower() == 'stuck':
        count = len(watched_trains)
    elif train_type.lower() == 'all':
        count = len(world_trains)
    elif train_type.lower() == 'cut':
        for tid in world_trains:
            if world_trains[tid].symbol == 'NON_LEADER_LOCO':
                count += 1
    else:
        count = -1

    return count


def player_crew_train(train_set, tid, discord_id, discord_name, thread, add_time):
    if discord_id in players:
        return -1
    loco_num = train_set[tid].lead_num
    symbol = train_set[tid].symbol
    players[discord_id] = Player(discord_id, discord_name, thread, symbol, tid, loco_num, add_time)
    if tid not in players:
        train_set[tid].engineer = discord_name
        train_set[tid].discord_id = discord_id
        train_set[tid].job_thread = thread
        train_set[tid].last_time_moved = add_time
        return 0


def parseAEI(timestamp, root):
    this_report = None
    for t in root.iter('AEI_Report'):
        scanner_name = t.find('scannername').text
        train_symbol = t.find('trainsymbol').text
        train_speed = t.find('trainspeedmph').text
        total_axles = t.find('totalaxles').text
        total_loads = t.find('totalloads').text
        total_empties = t.find('totalmtys').text
        total_tons = t.find('totaltons').text
        total_length = t.find('trainlengthft').text
        units = list()
        unitLoader = t.find('reportdata')
        for rail_vehicle in unitLoader.iter('AEI_Report_UnitData'):
            unit_type = rail_vehicle.find('equipmentype').text
            direction = rail_vehicle.find('direction').text
            sequence = rail_vehicle.find('sequence').text
            roadname = rail_vehicle.find('roadname').text
            unitnumber = rail_vehicle.find('unitnumber').text
            isloaded = rail_vehicle.find('isloaded').text
            cargotons = rail_vehicle.find('cargotons').text
            hazmat = rail_vehicle.find('hazmatPlacardIndex').text
            dest_tag = rail_vehicle.find('destinationtag').text
            defect = rail_vehicle.find('cardefect').text
            file_name = rail_vehicle.find('carfilename').text
            units.append(
                CarReport(unit_type, direction, sequence, roadname, unitnumber, isloaded, cargotons, hazmat, dest_tag,
                          defect, file_name))
        this_report = AeiReport(scanner_name, timestamp, train_symbol, train_speed, total_axles, total_loads,
                                total_empties, total_tons, total_length, units)

    return this_report


def duplicate_symbol(trains, symbol):
    '''

    :param trains: dict of trains
    :param symbol: symbol to match
    :return: number of trains in the dict with that symbol
    '''
    count = 0
    for tid in trains:
        if trains[tid].symbol.lower() == symbol.lower():
            count += 1
    return count


def log_msg(msg):
    with open(LOG_FILENAME, 'a', encoding='utf-8') as fp:
        fp.write(msg + '\n')


def prettify(msg):
    header = msg.split('```')[0]
    body = msg.split('```')[1]
    entries = list()
    max_c1 = 0
    max_c2 = 0
    max_c3 = 0
    max_c4 = 0
    return_msg = header + '```'
    lines = body.split('\n')
    for line in lines:
        if '|' in line:
            entries.append(line.split('|'))
        else:
            return_msg += f'{line}\n'
    for entry in entries:
        max_c1 = max(max_c1, len(entry[0]))
        max_c2 = max(max_c2, len(entry[1]))
        max_c3 = max(max_c3, len(entry[2]))
        max_c4 = max(max_c4, len(entry[3]))
    for entry in entries:
        return_msg += f'{entry[0]: <{max_c1}}|{entry[1]: <{max_c2}}|{entry[2]: <{max_c3}}|{entry[3]: <{max_c4}}\n'
    return_msg = return_msg[:-1] + '```'

    return return_msg


def write_record(db, record):
    with open(db, 'a') as fp:
        fp.write(record + '\n')


def query_db_sum(db, query_field, query_value, result_field):
    total = 0.0
    with open(db, 'r') as fp:
        for line in fp:
            if int(line.split(',')[query_field]) == query_value:
                total += float(line.split(',')[result_field])
    return total


# Create event loop for Python 3.10+ compatibility
asyncio.set_event_loop(asyncio.new_event_loop())

bot = discord.Bot(intents=intents)


async def send_ch_msg(ch_name, ch_msg, log=True):
    """
    Send messages to discord channel
    :param ch_name: name of discord channel to write message to
    :param ch_msg: Message content
    :param log: whether to write messages to log file
    :return: 0 if successful, -1 if error
    """
    if ch_msg.lower() == 'none':
        return 0

    if len(ch_msg) > DISCORD_CHAR_LIMIT - 100:
        ch_msg = ch_msg[:DISCORD_CHAR_LIMIT - 100] + '[...truncated...]'

    for guild in bot.guilds:
        if isinstance(ch_name, str):
            for channel in guild.text_channels + guild.forum_channels:
                threads = channel.threads
                for thread in threads:
                    if thread.name.lower() == ch_name.lower():
                        try:
                            retval = await thread.send('[r8TE] ' + ch_msg)

                        except Exception as e:
                            ex_msg = f'Exception in scan_world_state/send_ch_msg(1): {e}'
                            print(ex_msg)
                            retval = -1

                        if log:
                            log_msg(ch_msg)
                        return retval

                if channel.name.lower() == ch_name.lower():
                    try:
                        retval = await channel.send('[r8TE] ' + ch_msg)

                    except Exception as e:
                        ex_msg = f'Exception in scan_world_state/send_ch_msg(2): {e}'
                        print(ex_msg)
                        retval = -1

                    if log:
                        log_msg(ch_msg)
                    return retval
        else:
            try:
                retval = await ch_name.send('[r8TE] ' + ch_msg)

            except Exception as e:
                ex_msg = f'Exception in scan_world_state/send_ch_msg channel name [{ch_name}] type error: {e}'
                print(ex_msg)
                retval = -1

            if log:
                log_msg(ch_msg)
            return retval

    print(f"[Warning] thread / channel {ch_name} not found.")
    return -1


async def strike_alert_msgs(target_channel, tid=None, update_message=None):
    # Strike out alert messages for a particular train or the entire channel
    if tid:  # This is a specific set of messages to delete
        if update_message:
            await send_ch_msg(target_channel, update_message)
            await asyncio.sleep(.3)
        for msg in alert_messages[tid]:  # Change previous alerts
            strike_it = False
            if RED_SQUARE in msg.content:
                new_content = msg.content.replace(RED_SQUARE, "").strip()
                strike_it = True
            elif RED_EXCLAMATION in msg.content:
                new_content = msg.content.replace(RED_EXCLAMATION, "").strip()
                strike_it = True
            if strike_it:
                # Don't double-strikethrough
                if not (new_content.startswith("~~") and new_content.endswith("~~")):  # noqa
                    new_content = f"~~{new_content}~~"

                try:
                    await msg.edit(content=new_content)
                    await asyncio.sleep(.3)

                except discord.Forbidden:
                    print(f"Missing permissions to edit message ID {msg.id}.")
                except discord.HTTPException as e:
                    print(f"Failed to edit message ID {msg.id}: {e}")

                await msg.edit(content=new_content)
        del alert_messages[tid]
        return
    else:  # We are removing (striking out) all messages in the channel
        for guild in bot.guilds:
            for channel in guild.text_channels + guild.forum_channels:
                if channel.name == target_channel:
                    strike_it = False
                    async for message in channel.history(limit=100):
                        if RED_SQUARE in message.content:
                            new_content = message.content.replace(RED_SQUARE, "").strip()
                            strike_it = True
                        elif RED_EXCLAMATION in message.content:
                            new_content = message.content.replace(RED_EXCLAMATION, "").strip()
                            strike_it = True
                        elif GREEN_CIRCLE in message.content:
                            new_content = message.content.replace(GREEN_CIRCLE, "").strip()
                            strike_it = True
                        elif AXE in message.content:
                            new_content = message.content.replace(AXE, "").strip()
                            strike_it = True

                        if strike_it:
                            # Don't double-strikethrough
                            if not (new_content.startswith("~~") and new_content.endswith("~~")):  # noqa
                                new_content = f"~~{new_content}~~"
                            strike_it = False

                            try:
                                await message.edit(content=new_content)
                                await asyncio.sleep(.3)

                            except discord.Forbidden:
                                print(f"Missing permissions to edit message ID {message.id}.")
                            except discord.HTTPException as e:
                                print(f"Failed to edit message ID {message.id}: {e}")


def run_discord_bot():
    @bot.event
    async def on_application_command(ctx: discord.ApplicationContext):
        """Runs whenever a slash command is invoked (before execution)."""
        global last_world_datetime

        command_name = ctx.command.name
        options = ctx.selected_options or {}

        if isinstance(options, list):
            # Pycord sometimes returns a list of dicts like [{'name': 'arg1', 'value': 'foo'}]
            normalized = {opt["name"]: opt["value"] for opt in options}
        elif isinstance(options, dict):
            normalized = options
        else:
            normalized = {}

        msg = f'{last_world_datetime} {ctx.author} executed `/{command_name}'
        if len(normalized.keys()) > 0:
            msg += f' {", ".join(str(v) for v in normalized.values())}'
        msg += f'` in channel *{ctx.channel}*   :eyes:'
        await send_ch_msg(CH_LOG, msg)

    async def change_thread_tags(ctx: discord.ApplicationContext,
                                 tags_to_add: list, tags_to_remove: list | str | None = 'None'):
        thread = ctx.channel
        if not isinstance(thread, discord.Thread) or not isinstance(thread.parent, discord.ForumChannel):
            await ctx.respond('This command must be used inside a job post thread.', ephemeral=True)
            # Is it kosher for this function to write straight into the thread?
            return -1  # Indicate an error occurred
        forum_channel = thread.parent
        current_tags = thread.applied_tags or []

        # Get the id(s) of the tags to add
        if isinstance(tags_to_remove, list):
            for tag in tags_to_remove:
                check_tag = discord.utils.find(lambda t: t.name.lower() == tag.lower(), forum_channel.available_tags)
                if not check_tag:
                    await ctx.respond(f'[r8TE] **ERROR**: Tag `{check_tag}` not found in this forum.', ephemeral=True)
                    return -1
                else:
                    if check_tag in current_tags:
                        current_tags.remove(check_tag)
        elif tags_to_remove.lower() == 'all':
            current_tags.clear()  # Calling code wants to delete all current tags
        # Else don't remove any
        for tag in tags_to_add:
            check_tag = discord.utils.find(lambda t: t.name.lower() == tag.lower(), forum_channel.available_tags)
            if not check_tag:
                await ctx.respond(f'[r8TE] **ERROR**: Tag `{check_tag}` not found in this forum.', ephemeral=True)
                return -1
            else:
                if check_tag not in current_tags:
                    current_tags.append(check_tag)
        try:
            await thread.edit(applied_tags=current_tags)

        except discord.Forbidden:
            await ctx.respond('[r8TE] **ERROR**: I do not have permission to edit this thread.', ephemeral=True)
        except Exception as e:
            await ctx.respond(f'[r8TE] **ERROR**: {e}', ephemeral=True)

    @bot.slash_command(name='mark_available', description="Mark job as Available")
    @option("loco_num", description="Lead loco number", required=True)
    @option("location", description="Train location", required=True)
    @option("train_symbol", description="Train symbol", required=False)
    @option("train_info", description="Train info (", required=False)
    async def mark_available(ctx: discord.ApplicationContext, loco_num: str, location: str,
                             train_symbol: str, train_info: str):
        global last_world_datetime
        global working_jobs

        thread = ctx.channel
        if not isinstance(thread, discord.Thread) or not isinstance(thread.parent, discord.ForumChannel):
            await ctx.respond('This command must be used inside a job post thread.', ephemeral=True)
            return
        await change_thread_tags(ctx, [AVAILABLE_TAG], 'ALL')
        symbol_msg = 'Train symbol'
        num_msg = 'Lead loco number'
        info_msg = 'Train info'
        location_msg = 'Departure location(s)'
        txt_len = max(len(symbol_msg), len(num_msg), len(info_msg), len(location_msg))

        job_post = '```'
        if train_symbol:
            job_post += f'{symbol_msg: <{txt_len}} : {train_symbol}\n'
        job_post += f'{num_msg: <{txt_len}} : {loco_num}\n'
        if train_info:
            job_post += f'{info_msg: <{txt_len}} : {train_info}\n'
        job_post += f'{location_msg: <{txt_len}} : {location}\n'
        job_post += '```'
        try:
            await ctx.respond(job_post, ephemeral=False)

        except discord.Forbidden:
            await ctx.respond('[r8TE] **ERROR**: I do not have permission to edit this thread.', ephemeral=True)
        except Exception as e:
            await ctx.respond(f'[r8TE] **ERROR**: {e}', ephemeral=True)

    @bot.slash_command(name='staff_help', description="Mark job as needing staff attention")
    @option("note", description="Describe the issue", required=False)
    async def staff_help(ctx: discord.ApplicationContext, note: str):
        global last_world_datetime
        global working_jobs

        thread = ctx.channel
        # thread_id = ctx.channel.id
        # thread_name = ctx.channel.name
        if not isinstance(thread, discord.Thread) or not isinstance(thread.parent, discord.ForumChannel):
            await ctx.respond('This command must be used inside a job post thread.', ephemeral=True)
            return
        # thread_name = ctx.channel.name
        forum_channel = thread.parent
        await change_thread_tags(ctx, [STAFF_TAG], 'ALL')

        help_post = f'```ansi\n\u001b[2;31m'
        help_post += f'USER {ctx.author.display_name} HAS MARKED THIS JOB AS NEEDING STAFF ATTENTION'
        if note:
            help_post += f'\nNote(s): {note}'
        help_post += '\n\u001b[0m```'
        try:
            await ctx.respond(help_post, ephemeral=False)

        except discord.Forbidden:
            await ctx.respond('[r8TE] **ERROR**: I do not have permission to edit this thread.', ephemeral=True)
        except Exception as e:
            await ctx.respond(f'[r8TE] **ERROR**: {e}', ephemeral=True)

    @bot.slash_command(name='player_record', description="Show player how many hours they have logged in total.")
    async def player_record(ctx: discord.ApplicationContext):
        work_total = query_db_sum(PLAYER_DB_FILENAME, 0, ctx.author.id, 5)
        await ctx.respond(f'[r8TE] Effort total for {ctx.author.display_name} is **{work_total}** hours.',
                          ephemeral=True)

    @bot.slash_command(name='crew', description=f"Crew a train")
    @option("symbol", description="Train symbol", required=True)
    async def crew(ctx: discord.ApplicationContext, symbol: str):
        global last_world_datetime
        global working_jobs

        thread = ctx.channel
        thread_id = ctx.channel.id
        thread_name = ctx.channel.name

        if not isinstance(thread, discord.Thread) or not isinstance(thread.parent, discord.ForumChannel):
            await ctx.respond('This command must be used inside a job post thread.', ephemeral=True)
            return

        try:
            await ctx.respond(f'Attempting to crew train {symbol}', ephemeral=True)
            nbr_of_symbols = duplicate_symbol(curr_trains, symbol)
            if nbr_of_symbols > 1:
                await ctx.respond(f'**UNABLE TO CREW** : Train symbol "{symbol}" '
                                  f'found on {nbr_of_symbols} trains.', ephemeral=True)
                return
            tid = find_tid_by_symbol(symbol, curr_trains)
            if tid != -1:  # Train ID found
                if curr_trains[tid].engineer.lower() == 'none':
                    if player_crew_train(curr_trains, tid, ctx.author.id, ctx.author.display_name, thread_id,
                                         last_world_datetime) < 0:
                        await ctx.respond(f'**UNABLE TO CREW** : You are currently listed as crewing'
                                          f' [{players[ctx.author.mention].train_symbol}]**', ephemeral=True)
                        return
                    try:
                        working_jobs[thread_id].crew.append(ctx.author.display_name)
                    except KeyError:
                        working_jobs[thread_id] = Job(thread_name, [ctx.author.display_name])

                    msg = f'{curr_trains[tid].last_time_moved} {ctx.author.display_name} '
                    if len(working_jobs[thread_id].crew) > 1:
                        msg += f'crewed {curr_trains[tid].symbol}, assisting on job: *{thread_name}*'
                    else:
                        msg += f'crewed {curr_trains[tid].symbol}, working job: *{thread_name}*'
                    await change_thread_tags(ctx, [CREWED_TAG], [AVAILABLE_TAG])
                    await thread.send(msg)
                    # Update job ledger; First see if we have already created a ledger entry
                    job_name = None
                    async for message in thread.history(limit=None):  # Walk through thread looking for ledger entry
                        if 'JOBID#' in message.content:
                            job_name = message.content.split('JOBID# `')[1].split('`')[0]
                    if job_name:
                        ledger_channel = discord.utils.get(ctx.guild.channels, name=JOB_TRACK_FORUM)
                        ledger_thread = None  # Just in case we can't find the job thread
                        for test_thread in ledger_channel.threads:
                            if test_thread.name == job_name:
                                ledger_thread = test_thread
                        if ledger_thread is None:
                            err_msg = (f'[r8TE JOB ADMIN] **Error crewing job** : JobID [{job_name}] found, '
                                       f'but no associated thread found.')
                            await thread.send(err_msg)
                    else:  # No existing job ID thread found, so make a new one
                        ledger_channel = discord.utils.get(ctx.guild.channels, name=JOB_TRACK_FORUM)
                        job_id = datetime.now().strftime('%y%m%d-%H%M%S') + datetime.now().strftime('%f')[:2]
                        job_id += f' | {thread_name}'
                        ledger_embed = discord.Embed(title='Job Effort Ledger', color=discord.Color.blue())
                        ledger_embed.add_field(name='Job Title', value=thread_name, inline=False)
                        ledger_embed.add_field(name='Link', value=f'<#{thread.id}>', inline=False)
                        ledger_embed.description = f'```---- Effort ledger ----```'
                        ledger_thread = await ledger_channel.create_thread(name=job_id,
                                                                           embed=ledger_embed)
                        no_job_msg = (f'[r8TE JOB ADMIN] {last_world_datetime} '
                                      f'NEW LEDGER JOBID# `{job_id}`   <#{ledger_thread.id}>')
                        await thread.send(no_job_msg)
                    embed_msg = discord.Embed(title='CREW RECORD', color=discord.Color.green())
                    embed_msg.add_field(name='__Employee__', value=str(ctx.author.display_name), inline=False)
                    embed_msg.add_field(name='__Activity__', value='CREW (CLOCK IN)', inline=False)
                    embed_msg.add_field(name='__Time__', value=str(last_world_datetime), inline=False)
                    await ledger_thread.send(embed=embed_msg)
                    # Edit summary at top of thread
                    first_msg = await ledger_thread.history(limit=1, oldest_first=True).flatten()
                    msg_obj = first_msg[0]
                    # Check if this is a new embed-based ledger or old text-based ledger
                    if msg_obj.embeds:
                        # New embed format
                        ledger_embed = msg_obj.embeds[0]
                        new_content = (ledger_embed.description[:-3] +
                                       f'\n{ctx.author.display_name} | CLOCK_IN | {last_world_datetime.strftime("%m/%d/%y %H:%M")} | 0.0```')
                        new_message = prettify(new_content)
                        ledger_embed.description = new_message
                        await msg_obj.edit(embed=ledger_embed)
                    else:
                        # Old plain text format
                        new_content = (msg_obj.content[:-3] +
                                       f'\n{ctx.author.display_name} | CLOCK_IN | {last_world_datetime.strftime("%m/%d/%y %H:%M")} | 0.0```')
                        new_message = prettify(new_content)
                        await msg_obj.edit(content=new_message)

                else:
                    await ctx.respond(f'**UNABLE TO CREW, Train {symbol} shows '
                                      f'crewed by {curr_trains[tid].engineer}**', ephemeral=True)
            else:
                await ctx.respond(f'**UNABLE TO CREW**, Train *{symbol}* not found (if you recently changed locomotive '
                                  f'symbol/tag, please try again in about 2 minutes)', ephemeral=True)
        except discord.Forbidden:
            await ctx.respond('[r8TE] **ERROR** (*crew* command): no permission to edit this thread.', ephemeral=False)
        except Exception as e:
            await ctx.respond(f'[r8TE] **ERROR** (*crew* command): {e}', ephemeral=False)

    @bot.slash_command(name='tie_down', description=f"Tie down a train")
    @option("location", description="Tie-down location", required=True)
    async def tie_down(ctx: discord.ApplicationContext, location: str):
        thread = ctx.channel
        thread_id = ctx.channel.id
        thread_name = ctx.channel.name
        if not isinstance(thread, discord.Thread) or not isinstance(thread.parent, discord.ForumChannel):
            await ctx.respond('This command must be used inside a job post thread.', ephemeral=True)
            return
        try:
            await ctx.respond(f'Attempting to tie down', ephemeral=True)
            if ctx.author.id in players:
                if players[ctx.author.id].job_thread != thread_id:
                    msg = (f'**Unable to tie down** - incorrect job thread. Please execute the `/tie_down` '
                           f'command in <#{players[ctx.author.id].job_thread}>')
                    await ctx.respond(msg, ephemeral=True)
                    return
                tid = players[ctx.author.id].train_id
                orig_engineer = ctx.author.id
                orig_symbol = players[ctx.author.id].train_symbol
                if tid not in deleted_player_trains:  # Safe to update current train record
                    # Clear info from train record
                    curr_trains[tid].engineer = 'None'
                    curr_trains[tid].discord_id = None
                    curr_trains[tid].job_thread = None
                start_time = players[ctx.author.id].start_time
                del players[ctx.author.id]  # Remove this player record
                time_worked = round((last_world_datetime - start_time).total_seconds() / 3600, 1)
                # Check to see if this is a multi-crewed job
                if len(working_jobs[thread_id].crew) < 2:
                    # Single crew train
                    msg = (f'{ctx.author.display_name} tied down train '
                           f'{orig_symbol} at {location}\nTime worked: {time_worked} hours')
                    del working_jobs[thread_id]
                else:
                    # Multi-crew train
                    working_jobs[thread_id].crew.remove(ctx.author.display_name)
                    msg = (f'{ctx.author.display_name} tied down train '
                           f'{orig_symbol} at {location}\nTime worked: {time_worked} hours\n'
                           f'Job *{working_jobs[thread_id].name}* still being worked by:')
                    for player in working_jobs[thread_id].crew:
                        msg += f' {player},'
                    msg = msg[:-1]

                if tid in watched_trains:
                    # This train has a watch on it - time to remove, and strike-thru previous alert messages
                    alert_msg = (f' {GREEN_CIRCLE} {last_world_datetime} **TIED DOWN**: Train {orig_symbol}'
                                 f' ({tid}) has been tied down by {orig_engineer}')
                    await strike_alert_msgs(CH_ALERT, tid, alert_msg)
                    await asyncio.sleep(.3)
                    del watched_trains[tid]  # No longer need to watch
                # Update job ledger; First see if we have already created a ledger entry
                job_name = None
                async for message in thread.history(limit=None):  # Walk through thread looking for ledger entry
                    if 'JOBID#' in message.content:
                        job_name = message.content.split('JOBID# `')[1].split('`')[0]
                if job_name:
                    ledger_channel = discord.utils.get(ctx.guild.channels, name=JOB_TRACK_FORUM)
                    ledger_thread = None  # Just in case we can't find the job thread
                    for test_thread in ledger_channel.threads:
                        if test_thread.name == job_name:
                            ledger_thread = test_thread
                    if ledger_thread is None:
                        err_msg = (f'[r8TE JOB ADMIN] **Error tying down job** : JobID [{job_name}] found, '
                                   f'but no associated thread found.')
                        await thread.send(err_msg)
                else:  # No existing job ID thread found, so make a new one
                    ledger_channel = discord.utils.get(ctx.guild.channels, name=JOB_TRACK_FORUM)
                    job_id = datetime.now().strftime('%y%m%d-%H%M%S') + datetime.now().strftime('%f')[:2]
                    job_id += f' | {thread_name}'
                    ledger_embed = discord.Embed(title='Job Effort Ledger', color=discord.Color.blue())
                    ledger_embed.add_field(name='Job Title', value=thread_name, inline=False)
                    ledger_embed.add_field(name='Link', value=f'<#{thread.id}>', inline=False)
                    ledger_embed.description = f'```---- Effort ledger ----```'
                    ledger_thread = await ledger_channel.create_thread(name=job_id,
                                                                       embed=ledger_embed)
                    no_job_msg = (f'[r8TE JOB ADMIN] {last_world_datetime} '
                                  f'NEW LEDGER JOBID# `{job_id}`   <#{ledger_thread.id}>')
                    await thread.send(no_job_msg)
                embed_msg = discord.Embed(title='CREW RECORD', color=discord.Color.yellow())
                embed_msg.add_field(name='__Employee__', value=str(ctx.author.display_name), inline=False)
                embed_msg.add_field(name='__Activity__', value='TIE DOWN (CLOCK OUT)', inline=False)
                embed_msg.add_field(name='__Time__', value=str(last_world_datetime), inline=False)
                embed_msg.add_field(name='__Location__', value=str(location), inline=False)
                embed_msg.add_field(name='__Hours logged__', value=str(time_worked), inline=False)
                await ledger_thread.send(embed=embed_msg)
                # Edit summary at top of thread
                first_msg = await ledger_thread.history(limit=1, oldest_first=True).flatten()
                msg_obj = first_msg[0]
                # Check if this is a new embed-based ledger or old text-based ledger
                if msg_obj.embeds:
                    # New embed format
                    ledger_embed = msg_obj.embeds[0]
                    new_content = (ledger_embed.description[:-3] +
                                   f'\n{ctx.author.display_name} | CLOCK_OUT | {last_world_datetime.strftime("%m/%d/%y %H:%M")} | {time_worked}```')
                    new_message = prettify(new_content)
                    ledger_embed.description = new_message
                    await msg_obj.edit(embed=ledger_embed)
                else:
                    # Old plain text format
                    new_content = (msg_obj.content[:-3] +
                                   f'\n{ctx.author.display_name} | CLOCK_OUT | {last_world_datetime.strftime("%m/%d/%y %H:%M")} | {time_worked}```')
                    new_message = prettify(new_content)
                    await msg_obj.edit(content=new_message)
                # Give summary of hours player has worked
                employee = defaultdict(list)
                logs = new_message.split('```')[1].split('\n')  # Get the summary section
                for i in range(1, len(logs)):  # Create dict with work logs keyed on player name with list of hours
                    employee[logs[i].split('|')[0].strip().lower()].append(float(logs[i].split('|')[3].strip()))
                total = 0
                for time_worked in employee[ctx.author.display_name.lower()]:
                    total += time_worked
                msg += f'\n{ctx.author.display_name} has accrued {round(total, 2)} hours worked on this job.'
                # Create database entry
                job_name = ledger_thread.name.split('|')[1].strip()
                db_entry = (f'{ctx.author.id},{ctx.author.display_name},TIE_DOWN,{last_world_datetime},'
                            f'{job_name.replace(",", " ")},{time_worked}')
                write_record(PLAYER_DB_FILENAME, db_entry)
                await thread.send(msg)
                await change_thread_tags(ctx, [AVAILABLE_TAG], [CREWED_TAG])

                return
            else:
                await ctx.respond(f'**ERROR** Unable to tie-down: '
                                  f'You are not listed as crew on any train.', ephemeral=True)

        except discord.Forbidden:
            await ctx.respond('[r8TE] **ERROR** (*tie_down* command): no permission to edit this thread.',
                              ephemeral=False)
        except Exception as e:
            await ctx.respond(f'[r8TE] **ERROR** (*tie_down* command): {e}', ephemeral=False)

    @bot.slash_command(name='complete', description=f"Mark a job complete")
    @option('notes', description='completion notes', required=False)
    async def complete(ctx: discord.ApplicationContext, notes: str):
        thread = ctx.channel
        thread_id = ctx.channel.id
        thread_name = ctx.channel.name
        if not isinstance(thread, discord.Thread) or not isinstance(thread.parent, discord.ForumChannel):
            await ctx.respond('This command must be used inside a job post thread.', ephemeral=True)
            return
        try:
            await ctx.respond(f'Attempting to mark *{working_jobs[players[ctx.author.id].job_thread].name}'
                              f'* as complete.', ephemeral=True)
            if ctx.author.id in players:
                if ctx.author.id in players:
                    if players[ctx.author.id].job_thread != thread_id:
                        msg = (f'**Unable to mark this job complete** - incorrect job thread. Please execute the '
                               f'`/complete` command in <#{players[ctx.author.id].job_thread}>')
                        await ctx.respond(msg, ephemeral=True)
                        return
                job_complete = False
                tid = players[ctx.author.id].train_id
                orig_engineer = ctx.author.id
                orig_symbol = players[ctx.author.id].train_symbol
                if tid not in deleted_player_trains:  # Safe to update current train record
                    # Clear info from train record
                    curr_trains[tid].engineer = 'None'
                    curr_trains[tid].discord_id = None
                    curr_trains[tid].job_thread = None
                start_time = players[ctx.author.id].start_time
                del players[ctx.author.id]  # Remove this player record
                time_worked = round((last_world_datetime - start_time).total_seconds() / 3600, 1)
                # Update job ledger; First see if we have already created a ledger entry
                job_name = None
                async for message in thread.history(limit=None):  # Walk through thread looking for ledger entry
                    if 'JOBID#' in message.content:
                        job_name = message.content.split('JOBID# `')[1].split('`')[0]
                        ledger_link = message.content.split('JOBID# `')[1].split('`')[1]
                        # Replace this message since this job will no longer be worked
                        new_message = f'[r8TE JOB ADMIN] {last_world_datetime} JOB COMPLETE {job_name} {ledger_link}'
                        await message.edit(content=new_message)
                if job_name:
                    ledger_channel = discord.utils.get(ctx.guild.channels, name=JOB_TRACK_FORUM)
                    ledger_thread = None  # Just in case we can't find the job thread
                    for test_thread in ledger_channel.threads:
                        if test_thread.name == job_name:
                            ledger_thread = test_thread
                    if ledger_thread is None:
                        err_msg = (f'[r8TE JOB ADMIN] **Error completing job** : JobID [{job_name}] found, '
                                   f'but no associated thread found.')
                        await thread.send(err_msg)

                else:  # No existing job ID thread found, so make a new one
                    ledger_channel = discord.utils.get(ctx.guild.channels, name=JOB_TRACK_FORUM)
                    job_id = datetime.now().strftime('%y%m%d-%H%M%S') + datetime.now().strftime('%f')[:2]
                    job_id += f' | {thread_name}'
                    ledger_embed = discord.Embed(title='Job Effort Ledger', color=discord.Color.blue())
                    ledger_embed.add_field(name='Job Title', value=thread_name, inline=False)
                    ledger_embed.add_field(name='Link', value=f'<#{thread.id}>', inline=False)
                    ledger_embed.description = f'```---- Effort ledger ----```'
                    ledger_thread = await ledger_channel.create_thread(name=job_id,
                                                                       embed=ledger_embed)
                    no_job_msg = (f'[r8TE JOB ADMIN] {last_world_datetime} '
                                  f'NEW LEDGER JOBID# `{job_id}`   <#{ledger_thread.id}>')
                    await thread.send(no_job_msg)

                # Check to see if this is a multi-crewed job, if so we are really just tying down
                if len(working_jobs[thread_id].crew) < 2:
                    # Single crew train
                    msg = (f'{ctx.author.display_name} tied down train {orig_symbol}, and marked job '
                           f'*{working_jobs[thread_id].name}* `{COMPLETED_TAG}`\nTime worked: {time_worked} hours')
                    embed_msg = discord.Embed(title='CREW RECORD', color=discord.Color.orange())
                    embed_msg.add_field(name='__Employee__', value=str(ctx.author.display_name), inline=False)
                    embed_msg.add_field(name='__Activity__', value='MARK COMPLETE (CLOCK OUT)', inline=False)
                    embed_msg.add_field(name='__Time__', value=str(last_world_datetime), inline=False)
                    if notes:
                        embed_msg.add_field(name='__Employee note(s)__', value=str(notes), inline=False)
                    embed_msg.add_field(name='__Hours logged__', value=str(time_worked), inline=False)
                    # Edit summary at top of thread
                    first_msg = await ledger_thread.history(limit=1, oldest_first=True).flatten()
                    msg_obj = first_msg[0]
                    ledger_embed = None
                    # Check if this is a new embed-based ledger or old text-based ledger
                    if msg_obj.embeds:
                        # New embed format
                        ledger_embed = msg_obj.embeds[0]
                        new_content = (ledger_embed.description[:-3] +
                                       f'\n{ctx.author.display_name} | CLOCK_OUT | '
                                       f'{last_world_datetime.strftime("%m/%d/%y %H:%M")} | {time_worked}```')
                    else:
                        # Old plain text format
                        new_content = (msg_obj.content[:-3] +
                                       f'\n{ctx.author.display_name} | CLOCK_OUT | '
                                       f'{last_world_datetime.strftime("%m/%d/%y %H:%M")} | {time_worked}```')
                    # Create database entry
                    job_name = ledger_thread.name.split('|')[1].strip()
                    db_entry = (f'{ctx.author.id},{ctx.author.display_name},COMPLETE,{last_world_datetime},'
                                f'{job_name.replace(",", " ")},{time_worked}')
                    write_record(PLAYER_DB_FILENAME, db_entry)
                    del working_jobs[thread_id]
                    job_complete = True
                    await change_thread_tags(ctx, [COMPLETED_TAG], 'ALL')
                else:
                    # Multi-crew, so tie down instead - no need to change thread tags
                    working_jobs[thread_id].crew.remove(ctx.author.display_name)  # Remove player from job list
                    msg = (f'{ctx.author.display_name} tied down train {orig_symbol}\nTime worked: '
                           f'{time_worked} hours\n Job *{working_jobs[thread_id].name}* still being worked by:')
                    for player in working_jobs[thread_id].crew:
                        msg += f' {player},'
                    msg = msg[:-1]
                    embed_msg = discord.Embed(title='CREW RECORD', color=discord.Color.yellow())
                    embed_msg.add_field(name='__Employee__', value=str(ctx.author.display_name), inline=False)
                    embed_msg.add_field(name='__Activity__', value='TIE DOWN (CLOCK OUT)', inline=False)
                    embed_msg.add_field(name='__Time__', value=str(last_world_datetime), inline=False)
                    embed_msg.add_field(name='__Administrative Note__',
                                        value=str('*Employee attempted to mark a multi-crewed job as complete*'),
                                        inline=False)
                    if notes:
                        embed_msg.add_field(name='__Employee note(s)__', value=str(notes), inline=False)
                    embed_msg.add_field(name='__Hours logged__', value=str(time_worked), inline=False)
                    # Edit summary at top of thread
                    first_msg = await ledger_thread.history(limit=1, oldest_first=True).flatten()
                    msg_obj = first_msg[0]
                    ledger_embed = None
                    # Check if this is a new embed-based ledger or old text-based ledger
                    if msg_obj.embeds:
                        # New embed format
                        ledger_embed = msg_obj.embeds[0]
                        new_content = (ledger_embed.description[:-3] +
                                       f'\n{ctx.author.display_name} | CLOCK_OUT | '
                                       f'{last_world_datetime.strftime("%m/%d/%y %H:%M")} | {time_worked}```')
                    else:
                        # Old plain text format
                        new_content = (msg_obj.content[:-3] +
                                       f'\n{ctx.author.display_name} | CLOCK_OUT | '
                                       f'{last_world_datetime.strftime("%m/%d/%y %H:%M")} | {time_worked}```')
                    # Create database entry
                    job_name = ledger_thread.name.split('|')[1].strip()
                    db_entry = (f'{ctx.author.id},{ctx.author.display_name},TIE_DOWN,{last_world_datetime},'
                                f'{job_name.replace(",", " ")},{time_worked}')
                    write_record(PLAYER_DB_FILENAME, db_entry)
                if notes:
                    msg += f'\nNotes: {notes}'
                # Give summary of hours player has worked
                employee = defaultdict(list)
                logs = new_content.split('```')[1].split('\n')  # Get the summary section
                for i in range(1, len(logs)):  # Create dict with work logs keyed on player name with list of hours
                    employee[logs[i].split('|')[0].strip()].append(float(logs[i].split('|')[3].strip()))
                total = 0
                for time_increment in employee[ctx.author.display_name]:
                    total += time_increment
                msg += f'\n{ctx.author.display_name} has accrued {round(total, 2)} hours on this job.'
                new_message = prettify(new_content)
                if job_complete:
                    # Since job has completed, we also sum all the work done and update the job ledger
                    total_time = 0
                    new_message = new_message[:-3] + '\n\n---- Job complete, effort summary below ----'
                    name_len = len(max(employee, key=len))
                    for key in employee.keys():
                        employee_time = 0
                        for time_worked in employee[key]:
                            employee_time += time_worked
                            total_time += time_worked
                        new_message += f'\n{key: <{name_len}}: {round(employee_time, 2)} hours'
                    new_message += f'\n\nTotal time worked on this job: {round(total_time, 2)} hours```'
                    job_num = ledger_thread.name.split('|')[0].strip()
                    job_entry = f'{job_name.replace(",", " ")},{job_num},{last_world_datetime},{round(total_time, 2)}'
                    write_record(JOB_DB_FILENAME, job_entry)
                # Edit the ledger message with the updated content
                if ledger_embed is not None:
                    # New embed format
                    ledger_embed.description = new_message
                    await msg_obj.edit(embed=ledger_embed)
                else:
                    # Old plain text format
                    await msg_obj.edit(content=new_message)
                await thread.send(msg)
                await ledger_thread.send(embed=embed_msg)
                if tid in watched_trains:
                    # This train has a watch on it - time to remove, and strike-thru previous alert messages
                    msg = (f' {GREEN_CIRCLE} {last_world_datetime} **POWERED DOWN**: Train {orig_symbol}'
                           f' ({tid}) has been tied down by {orig_engineer}')
                    await strike_alert_msgs(CH_ALERT, tid, msg)
                    await asyncio.sleep(.3)
                    del watched_trains[tid]  # No longer need to watch

                return
            else:
                await ctx.respond(f'Unable to mark as complete; are you sure you are clocked in?', ephemeral=True)
        except discord.Forbidden:
            await ctx.respond('[r8TE] **ERROR** (*complete* command): no permission to edit this thread.',
                              ephemeral=False)
        except Exception as e:
            await ctx.respond(f'[r8TE] **ERROR** (*complete* command): {e}', ephemeral=False)

    @bot.slash_command(name="r8te_clear_crew", description="Remove player from crew status")
    @option('player_id', description='Player ID', required=True)
    async def r8te_clear_crew(ctx: discord.ApplicationContext, player: discord.Member):
        if player.id not in players:
            await ctx.respond(f'[r8TE] **ERROR**: Unable to find {player} ({player.id}) in crewed train list')
            return
        tid = players[player.id].train_id
        thread = await bot.fetch_channel(curr_trains[tid].job_thread)
        orig_engineer = curr_trains[tid].engineer
        # Clear info from train record
        curr_trains[tid].engineer = 'none'
        curr_trains[tid].discord_id = None
        curr_trains[tid].job_thread = None
        del players[player.id]  # Remove this player record
        if len(working_jobs[thread.id].crew) > 1:
            working_jobs[thread.id].crew.remove(player.display_name)  # Remove player from list of crew
        else:
            del working_jobs[thread.id]  # Remove job record
        msg = (f'{curr_trains[tid].last_time_moved} **Admin** tied this train down: '
               f'{curr_trains[tid].symbol} [{orig_engineer}]')
        await thread.send(msg)
        await send_ch_msg(CH_LOG, msg)
        await ctx.respond(msg, ephemeral=True)
        await asyncio.sleep(.3)
        # await thread.edit(applied_tags=current_tags)

        if tid in watched_trains:
            # This train has a watch on it - time to remove, and strike-thru previous alert messages
            msg = (f' {GREEN_CIRCLE} {last_world_datetime} **ADMIN TIED DOWN**: Train {curr_trains[tid].symbol}'
                   f' ({tid}) has been tied down by a staff/admin')
            await strike_alert_msgs(CH_ALERT, tid, msg)
            await asyncio.sleep(.3)
            del watched_trains[tid]  # No longer need to watch
        return

    @bot.slash_command(name="r8te_clear_job", description="Clear job from queue")
    @option('player_id', description='Player ID', required=True)
    async def r8te_clear_job(ctx: discord.ApplicationContext, job_name: str):
        msg = f'Job {job_name} not found'
        for job in working_jobs:
            if working_jobs[job].name == job_name:
                del working_jobs[job]
                msg = f'Job "{job_name}" has been cleared'
                break
        await ctx.respond(msg, ephemeral=True)
        return

    @bot.slash_command(name="r8te_list_trains", description="List trains")
    @option('list_type', description='type of list (ai, player, idle, stuck)', required=True)
    async def r8te_list_trains(ctx: discord.ApplicationContext, list_type: str):
        msg = ''
        if list_type.lower() == 'player':
            for player in players:
                tid = players[player].train_id
                if players[player].train_symbol != curr_trains[tid].symbol:
                    msg += (f'{players[player].discord_name} :'
                            f' **Inconsistent lead unit** // Orig leader: {players[player].train_symbol} // '
                            f' Curr leader: {curr_trains[tid].symbol} //')
                else:
                    msg += f'{players[player].discord_name} : {curr_trains[tid].symbol}'
                msg += f' [{tid}] # {curr_trains[tid].lead_num}, Units: {curr_trains[tid].num_units}\n'

        else:
            for tid in curr_trains:
                if list_type.lower() == 'ai':
                    if curr_trains[tid].engineer.lower() == 'ai':
                        msg += (f'{curr_trains[tid].symbol} [{tid}] # {curr_trains[tid].lead_num},'
                                f' Units: {curr_trains[tid].num_units}\n')
                elif list_type.lower() == 'stuck':
                    if tid in watched_trains:
                        td = last_world_datetime - curr_trains[tid].last_time_moved
                        msg += f'{curr_trains[tid].engineer}'
                        msg += (f' : {curr_trains[tid].symbol} [{tid}] # {curr_trains[tid].lead_num},'
                                f' # {curr_trains[tid].lead_num}, Units: {curr_trains[tid].num_units}, Stopped for: {td},'
                                f' DLC {location(curr_trains[tid].route_1, curr_trains[tid].track_1)}\n')
                else:
                    if curr_trains[tid].engineer.lower() == 'none':
                        msg += (f'{curr_trains[tid].symbol} [{tid}] # {curr_trains[tid].lead_num},'
                                f' Units: {curr_trains[tid].num_units}\n')
        if len(msg) < 1:
            msg = f'No {list_type} trains found.'
        if len(msg) > DISCORD_CHAR_LIMIT:
            tf = open(TMP_FILENAME, 'w')
            tf.write(msg)
            tf.close()
            await ctx.response.send_message(file=discord.File(TMP_FILENAME), ephemeral=True)
        else:
            await ctx.respond(msg, ephemeral=True)
        # await ctx.respond(msg, ephemeral=True)

    @bot.slash_command(name='r8te_train_info', description="Display info of individual train")
    @option('tid', required=True, description='Train ID')
    async def r8te_train_info(ctx: discord.ApplicationContext, tid: int):
        if tid in curr_trains:
            msg = curr_trains[tid]
        else:
            msg = f'Train {tid} not found.'
        await ctx.respond(msg, ephemeral=True)

    @bot.slash_command(name='r8te_list_jobs', description="Display list of jobs being worked")
    async def r8te_list_jobs(ctx: discord.ApplicationContext):
        global working_jobs

        msg = ''
        if len(working_jobs) == 0:
            msg = f'No jobs being worked.'
        else:
            i = 1
            for job in working_jobs.values():
                msg += f'{i} : {str(job)}\n'
                i += 1
            msg = msg[:-1]
        await ctx.respond(msg, ephemeral=True)

    @bot.slash_command(name='r8te_consist_info', description="Display symbols of all cars in train")
    @option('tid', required=True, description='Train ID')
    async def r8te_consist_info(ctx: discord.ApplicationContext, tid: int):
        if tid in curr_trains:
            msg = '`'
            count = 1
            for car in curr_trains[tid].consist:
                msg += f'{count} : {car.dest_tag} | {car.filename.split(".")[0]}\n'
                count += 1
            msg += '`'
        else:
            msg = f'Train {tid} not found.'
        if len(msg) > DISCORD_CHAR_LIMIT:
            tf = open(TMP_FILENAME, 'w')
            tf.write(msg)
            tf.close()
            await ctx.response.send_message(file=discord.File(TMP_FILENAME), ephemeral=True)
        else:
            await ctx.respond(msg, ephemeral=True)

    @bot.slash_command(name="r8te_check_symbol", description="Check for existence of a train symbol")
    @option('symbol', description='symbol', required=True)
    async def r8te_check_symbol(ctx: discord.ApplicationContext, symbol: str):
        msg = ''
        for tid in curr_trains:
            if curr_trains[tid].symbol == symbol:
                msg += (f'({tid}) {curr_trains[tid].symbol} [#{curr_trains[tid].lead_num}] : '
                        f'{location(curr_trains[tid].route_1, curr_trains[tid].track_1)}\n')
        if len(msg) < 1:
            msg = f'Train {symbol} not found.'
        await ctx.respond(msg, ephemeral=True)

    @tasks.loop(seconds=SCAN_TIME)
    async def scan_world_state():
        global last_world_datetime
        global last_worlds_save_modified_time  # designated global to keep track between calls
        global status_timer
        global nbr_ai_added
        global nbr_ai_removed

        # Check for initial startup
        if not last_world_datetime:  # First time through - populate the world from nothing
            last_worlds_save_modified_time = os.stat(SAVENAME).st_mtime  # Time
            last_world_datetime, error_status = update_world_state(last_world_datetime, curr_trains)
            status_timer = datetime.now()
            nbr_ai_added = 0
            nbr_ai_removed = 0

            msg = (f'{last_world_datetime} **--> r8te ({VERSION}) INITIALIZING NEW WORLD STATE <--** '
                   f'Total number of trains: {train_count("all", curr_trains, watched_trains)} '
                   f'(AI trains: {train_count("ai", curr_trains, watched_trains)}, '
                   f'Mid-cut locos: {train_count("cut", curr_trains, watched_trains)}, '
                   f' player trains: {train_count("player", curr_trains, watched_trains)}) ')
            print(msg)
            await send_ch_msg(CH_LOG, msg)
            await strike_alert_msgs(CH_ALERT)  # Get rid of any chaff from previous alerts
            if error_status:
                msg = f'{last_world_datetime} {error_status}'
                print(msg)
                await send_ch_msg(CH_LOG, msg)

        # Check for server reboot
        elif (os.stat(SAVENAME).st_mtime - last_worlds_save_modified_time) > REBOOT_TIME:
            msg = f'{last_world_datetime} **Apparent server reboot** : Re-syncing train states.\n'
            status_timer = datetime.now()
            nbr_ai_added = 0
            nbr_ai_removed = 0

            # Look for and archive player trains and capture existing player records
            player_updates = list()
            for player in players.values():
                player_updates.append([player.discord_id,  # 0
                                       player.discord_name,  # 1
                                       player.train_symbol,  # 2
                                       player.train_id,  # 3
                                       player.job_thread,  # 4
                                       player.loco_num])  # 5

            msg += f'...Found {len(player_updates)} players crewing trains.'
            for player in player_updates:
                msg += f'\n....{player[1]} : {player[2]} [{player[3]}]'
            await send_ch_msg(CH_LOG, msg)
            await asyncio.sleep(.3)
            players.clear()  # Clear out the players dict; it will be repopulated below
            # Repopulate trains
            last_worlds_save_modified_time = os.stat(SAVENAME).st_mtime  # Time
            last_world_datetime, error_status = update_world_state(last_world_datetime, curr_trains)
            if error_status:
                msg = f'{last_world_datetime} {error_status}'
                print(msg)
                await send_ch_msg(CH_LOG, msg)
            # Re-add players
            for player in player_updates:
                tid = find_tid_by_symbol(player[2], curr_trains)  # Find new TID for previously crewed train
                if tid < 0:  # Can't find this train, so remove crewed status and notify user
                    msg = (f'During server reboot, player train {player[2]}[{player[3]}] not found;'
                           f' removing crew status for player {player[1]}')
                    # Send message in job thread notifying player of the problem
                    player_msg = (f'<#{player[0]}>, during a server reboot your job status '
                                  f'for {player[2]} was lost. Please notify staff (former TID = {player[3]}).\n\n')
                    player_msg += (f'**STAFF** : Please check status of player crew and jobs being worked.\n'
                                   f'*{player[1]}* should not be listed as crewing a train, nor working a job.\n'
                                   f'You will likely need to manually reset the tags for this job post.\n'
                                   f'Relevant commands: `/r8te_list_trains player` and `/r8te_list_jobs`')
                    forum_thread = await bot.fetch_channel(player[4])
                    try:
                        del working_jobs[player[4]]  # Remove from job queue
                    except KeyError:
                        pass
                    await send_ch_msg(forum_thread, player_msg)
                    await asyncio.sleep(.3)
                    if player[3] in watched_trains:
                        # This train has a watch on it - time to remove, and strike-thru previous alert messages
                        # We are a bit redundant here as the server restart handler will strike through all messages,
                        # but we also want to clear out the watched_trains entry.
                        remove_msg = (
                            f' {GREEN_CIRCLE} {last_world_datetime} **SERVER HICCUP**: Train {player[2]}'
                            f' ({tid}) has been removed after a server restart.')
                        await strike_alert_msgs(CH_ALERT, player[3], remove_msg)
                        await asyncio.sleep(.3)
                        del watched_trains[player[3]]  # No longer need to watch
                    await send_ch_msg(CH_LOG, msg)
                    await asyncio.sleep(.3)

                else:
                    player_crew_train(curr_trains, tid, player[0], player[1], player[4],
                                      last_world_datetime)
            player_updates.clear()
            watched_trains.clear()
            msg = (f'{last_world_datetime} **--> r8te ({VERSION}) INITIALIZING NEW WORLD STATE <--** '
                   f'Total number of trains: {train_count("all", curr_trains, watched_trains)} '
                   f'(AI trains: {train_count("ai", curr_trains, watched_trains)},'
                   f'Mid-cut locos: {train_count("cut", curr_trains, watched_trains)}, '
                   f' player trains: {train_count("player", curr_trains, watched_trains)}) ')
            print(msg)
            await send_ch_msg(CH_LOG, msg)
            await asyncio.sleep(.3)
            await strike_alert_msgs(CH_ALERT)  # Get rid of any chaff from previous alerts

        #
        # Begin scanning world saves
        #
        # Check time stamp on world save file for an updated version
        if os.stat(SAVENAME).st_mtime != last_worlds_save_modified_time:
            # Updated world save found
            last_worlds_save_modified_time = os.stat(SAVENAME).st_mtime
            last_trains = curr_trains.copy()  # Archive our current set of trains for comparison
            last_world_datetime, error_status = update_world_state(last_world_datetime,
                                                                   curr_trains)  # Update the trains dictionary
            if error_status:
                msg = f'{last_world_datetime} {error_status}'
                print(msg)
                await send_ch_msg(CH_LOG, msg)

            # Check to see if any trains have been deleted
            trains_removed = list()
            deleted_train_list = list()

            for tid in last_trains:
                if tid not in curr_trains:
                    trains_removed.append(tid)
                    nbr_ai_removed += 1
                    eng_name = last_trains[tid].engineer
                    # msg = f'{last_world_datetime} Train removed: {last_trains[tid].symbol} [{eng_name}] ({tid})'
                    # await send_ch_msg(CH_LOG, msg)
                    # await asyncio.sleep(.3)
                    # Check if deleted train is in the watched train list
                    if tid in watched_trains:
                        msg = (f' {AXE} {last_world_datetime} **TRAIN DELETED**:'
                               f' [{last_trains[tid].engineer}] {last_trains[tid].symbol} ({tid}) has been deleted.')
                        await strike_alert_msgs(CH_ALERT, tid, msg)
                        await asyncio.sleep(.3)
                        del watched_trains[tid]  # No longer need to watch
                    # Check if deleted train is in the player list
                    # Here we want to note the time the train was deleted. Another section of code will handle the
                    #  actual deletion of the player and job record after a timeout.
                    for player in players:
                        if players[player].train_id == tid:
                            deleted_player = player
                            deleted_job = None
                            for job in working_jobs:
                                for name in working_jobs[job].crew:
                                    if name == players[player].discord_name:
                                        deleted_job = job
                            deleted_player_trains[tid] = DeletedTrainWatch(tid, last_world_datetime,
                                                                           last_trains[tid].symbol,
                                                                           deleted_player, deleted_job)
                            msg = (f'{last_world_datetime} Crewed Train {players[player].train_symbol} '
                                   f'[{players[player].discord_name}] missing from latest world save. '
                                   f'Watching to see if it respawns in the next {PLAYER_RESPAWN_TIME} seconds.')
                            await send_ch_msg(CH_LOG, msg)
                            await asyncio.sleep(.3)

            # Run through the deleted_player_trains list to determine if it's really time to nuke them
            # First determine if the player or job has been removed from their respective lists
            remove_deleted_train_list = list()
            for deleted_train in deleted_player_trains:
                if (deleted_player_trains[deleted_train].discord_id not in players
                        or deleted_player_trains[deleted_train].job_id not in working_jobs):
                    remove_deleted_train_list.append(deleted_train)
                    msg = (f'{last_world_datetime} : Crewed train {deleted_player_trains[deleted_train].train_symbol} '
                           f'scheduled for timeout has been removed prematurely due to missing player-crew or job.')
                    await send_ch_msg(CH_LOG, msg)
                    await asyncio.sleep(.3)
            for list_entry in remove_deleted_train_list:
                del deleted_player_trains[list_entry]
            # Player and job are intact, so go ahead and check timer
            players_deleted = list()
            jobs_deleted = list()
            player_trains_deleted = list()
            for tid in deleted_player_trains:
                t_diff = (last_world_datetime - deleted_player_trains[tid].delete_time).total_seconds()
                msg = (
                    f'{last_world_datetime} Checking deleted crewed train queue: '
                    f'{deleted_player_trains[tid].train_symbol} | {int(t_diff)} / {PLAYER_RESPAWN_TIME}')
                await send_ch_msg(CH_LOG, msg)
                await asyncio.sleep(.3)
                if t_diff > PLAYER_RESPAWN_TIME:
                    for player in players:
                        if players[player].train_id == tid:
                            players_deleted.append(player)
                            # Find job associated with this player
                            for job in working_jobs:
                                for name in working_jobs[job].crew:
                                    if name == players[player].discord_name:
                                        working_jobs[job].crew.remove(name)
                                if len(working_jobs[job].crew) == 0:
                                    jobs_deleted.append(job)
                            msg = (f' {last_world_datetime} **TRAIN INFO LOST**: [{players[player].discord_name}] '
                                   f'{players[player].train_symbol} ({tid}) has been deleted. \n'
                                   f'*Manually re-tagging post may be necessary* (contact staff if so).')
                            forum_thread = await bot.fetch_channel(players[player].job_thread)
                            await send_ch_msg(forum_thread, msg)
                            await asyncio.sleep(.3)
                            msg = (f'{last_world_datetime} Crewed train deleted due to timer expired:'
                                   f' [{players[player].discord_name}] {players[player].train_symbol}')
                            await send_ch_msg(CH_LOG, msg)
                            await asyncio.sleep(.3)
                            player_trains_deleted.append(tid)
                    for player in players_deleted:
                        del players[player]
                    for job in jobs_deleted:
                        del working_jobs[job]
            for tid in player_trains_deleted:
                del deleted_player_trains[tid]
            # Run through the deleted_player_trains list to determine if any have respawned with same symbol
            for tid in deleted_player_trains:
                if tid not in deleted_train_list:
                    new_tid = find_tid_by_symbol(deleted_player_trains[tid].train_symbol, curr_trains)
                    if new_tid == 0:
                        new_tid = find_tid_by_loco_num(deleted_player_trains[tid].loco_num, curr_trains)
                        if new_tid > 0:
                            msg = (f'Found a new TID based on loco #{deleted_player_trains[tid].loco_num}\n'
                                   f'Old TID: {deleted_player_trains[tid].train_id}, New TID: {new_tid}')
                            await send_ch_msg(CH_LOG, msg)
                            await asyncio.sleep(.3)
                    if new_tid > 0:
                        msg = (f'{last_world_datetime} Crewed train {deleted_player_trains[tid].train_symbol} '
                               f'respawned as TID: {new_tid} (formally {deleted_player_trains[tid].train_id})')
                        await send_ch_msg(CH_LOG, msg)
                        await asyncio.sleep(.3)
                        # Adjust the tid for the player crewed entry
                        players[deleted_player_trains[tid].discord_id].train_id = new_tid
                        # remove this deleted_player_train entry
                        deleted_train_list.append(tid)

            # Run through the deleted_player_trains list to determine if they put the lead into another consist
            for tid in deleted_player_trains:
                if tid not in deleted_train_list:
                    new_tid = find_symbol_in_consist(deleted_player_trains[tid].train_symbol, curr_trains)
                    if new_tid:
                        msg_player = 'Unknown'
                        for player in players:
                            if players[player].train_id == tid:
                                msg_player = players[player].discord_name
                        msg_orig_sym = deleted_player_trains[tid].train_symbol
                        msg_new_tid = new_tid[0]
                        msg_orig_pos = new_tid[1]
                        msg_new_sym = curr_trains[new_tid[0]].symbol
                        msg = (f'{last_world_datetime} Crewed train {msg_orig_sym} [{msg_player}] '
                               f'has been found on {msg_new_sym} [{msg_new_tid}] at position {msg_orig_pos}. Removing from '
                               f'deleted train watch queue.')
                        await send_ch_msg(CH_LOG, msg)
                        await asyncio.sleep(.3)
                        # Adjust the tid for the player crewed entry
                        players[deleted_player_trains[tid].discord_id].train_id = new_tid[0]
                        # remove this deleted_player_train entry
                        deleted_train_list.append(tid)

            for tid in deleted_train_list:
                del deleted_player_trains[tid]
            deleted_train_list.clear()

            # Run through each player record and check that the symbol to tid correspondence hasn't changed
            # Also, populate player / job info on new train dict
            for player in players.values():
                if not any(deleted.discord_id == player.discord_id for deleted in deleted_player_trains.values()):
                    if player.train_symbol.lower() != curr_trains[player.train_id].symbol.lower():
                        new_tid = find_tid_by_symbol(player.train_symbol, curr_trains)
                        if new_tid > 0:
                            msg = (f'{last_world_datetime} Crewed train {player.train_symbol} [{player.discord_name}] '
                                   f'has changed ID from {player.train_id} to {new_tid}. Updating player record.')
                            player.train_id = new_tid
                            await send_ch_msg(CH_LOG, msg)
                            await asyncio.sleep(.3)
                    curr_trains[player.train_id].discord_id = player.discord_id
                    curr_trains[player.train_id].engineer = player.discord_name
                    curr_trains[player.train_id].job_thread = player.job_thread

            # Initialize summary counters
            nbr_ai_moving = 0
            nbr_player_moving = 0
            nbr_ai_stopped = 0
            nbr_player_stopped = 0

            for tid in curr_trains:
                # Check for new trains
                if tid not in last_trains:
                    nbr_ai_added += 1
                    # eng_name = curr_trains[tid].engineer
                    # msg = f'{last_world_datetime} Train spawned: {curr_trains[tid].symbol} [{eng_name}] ({tid})'
                    # await send_ch_msg(CH_LOG, msg)
                    # await asyncio.sleep(.3)

                # Check for moving AI or player trains
                elif (curr_trains[tid].engineer.lower() != 'none' and not  # Ignore static and special tags
                any(tag in curr_trains[tid].symbol.lower() for tag in IGNORED_TAGS)):
                    if (curr_trains[tid].route_1 != last_trains[tid].route_1
                            or curr_trains[tid].route_2 != last_trains[tid].route_2
                            or curr_trains[tid].track_1 != last_trains[tid].track_1
                            or curr_trains[tid].track_2 != last_trains[tid].track_2
                            or abs(curr_trains[tid].dist_1 - last_trains[tid].dist_1) > DISTANCE_JITTER
                            or abs(curr_trains[tid].dist_2 - last_trains[tid].dist_2) > DISTANCE_JITTER):
                        # train HAS MOVED since last update
                        if curr_trains[tid].engineer.lower() == 'ai':
                            nbr_ai_moving += 1
                        else:
                            nbr_player_moving += 1

                        if tid in watched_trains:
                            # This train has a watch on it - time to remove, and strike-thru previous alert messages
                            msg = (
                                f' {GREEN_CIRCLE} {last_world_datetime} **ON THE MOVE**: Train {curr_trains[tid].symbol}'
                                f' ({tid}) is now on the move after'
                                f' {last_world_datetime - last_trains[tid].last_time_moved}.')
                            await strike_alert_msgs(CH_ALERT, tid, msg)
                            await asyncio.sleep(.3)
                            del watched_trains[tid]  # No longer need to watch
                    elif (curr_trains[tid].route_1 == last_trains[tid].route_1
                          and curr_trains[tid].route_2 == last_trains[tid].route_2
                          and curr_trains[tid].track_1 == last_trains[tid].track_1
                          and curr_trains[tid].track_2 == last_trains[tid].track_2
                          and abs(curr_trains[tid].dist_1 - last_trains[tid].dist_1) < DISTANCE_JITTER
                          and abs(curr_trains[tid].dist_2 - last_trains[tid].dist_2) < DISTANCE_JITTER):
                        # train HAS NOT MOVED since last update
                        if curr_trains[tid].engineer.lower() == 'ai':
                            nbr_ai_stopped += 1
                        else:
                            nbr_player_stopped += 1
                        td = last_world_datetime - last_trains[tid].last_time_moved
                        if (curr_trains[tid].engineer.lower() == 'ai' and td > timedelta(minutes=AI_ALERT_TIME) or
                                curr_trains[tid].engineer.lower() != 'ai' and td > timedelta(
                                    minutes=PLAYER_ALERT_TIME)):
                            # The time this train has been stopped is large enough to alert
                            if tid not in watched_trains:  # First alert
                                watched_trains[tid] = [curr_trains[tid].last_time_moved, 1]
                                log_msg(f'Added {tid}: {curr_trains[tid].symbol} to watched trains')
                                alert_msg = f' {RED_SQUARE} {last_world_datetime} **POSSIBLE STUCK TRAIN**: '
                                alert_msg += (f' [{curr_trains[tid].engineer}] {curr_trains[tid].symbol} ({tid})'
                                              f' has not moved for {td}, '
                                              f'DLC {location(curr_trains[tid].route_1, curr_trains[tid].track_1)}.')
                                alert_messages[tid].append(await send_ch_msg(CH_ALERT, alert_msg))
                                await asyncio.sleep(.3)
                                if curr_trains[tid].engineer.lower() != 'ai':
                                    player_msg = (
                                        f'<@{curr_trains[tid].discord_id}>: You are currently crewing {curr_trains[tid].symbol},'
                                        f' yet your train has not moved for at least {td}. Should you tie down?')
                                    forum_thread = await bot.fetch_channel(curr_trains[tid].job_thread)
                                    alert_messages[tid].append(await send_ch_msg(forum_thread, player_msg))
                                    await asyncio.sleep(.3)
                            elif ((curr_trains[tid].last_time_moved - watched_trains[tid][0])
                                  // watched_trains[tid][1] > timedelta(minutes=REMINDER_TIME)):
                                watched_trains[tid][1] += 1
                                alert_msg = (f' {RED_EXCLAMATION} {last_world_datetime}'
                                             f' **STUCK TRAIN REMINDER # {watched_trains[tid][1] - 1}**: ')
                                alert_msg += (f'[{curr_trains[tid].engineer}] {curr_trains[tid].symbol} ({tid})'
                                              f' has not moved for {td}, '
                                              f'DLC {location(curr_trains[tid].route_1, curr_trains[tid].track_1)}.')
                                alert_messages[tid].append(await send_ch_msg(CH_ALERT, alert_msg))
                                await asyncio.sleep(.3)
                                if curr_trains[tid].engineer.lower() != 'ai':
                                    player_msg = (
                                        f'{curr_trains[tid].engineer}: You are currently crewing {curr_trains[tid].symbol},'
                                        f' yet your train has not moved for at least {td}. Should you tie down?')
                                    forum_thread = await bot.fetch_channel(curr_trains[tid].job_thread)
                                    alert_messages[tid].append(await send_ch_msg(forum_thread, player_msg))
                                    await asyncio.sleep(.3)
                            else:
                                pass  # We have already notified at least once, now backing off before another notice
                        curr_trains[tid].last_time_moved = last_trains[tid].last_time_moved
                        curr_trains[tid].job_thread = last_trains[tid].job_thread
                    else:
                        print(f'something odd in comparing these two:\n{curr_trains[tid]}\n{last_trains[tid]}')

            td = datetime.now() - status_timer
            if td.seconds > STATUS_REPORT_TIME * 60:  # Send status update
                status_timer = datetime.now()
                msg = (f'{last_world_datetime} Summary: AI ({nbr_ai_moving}M, {nbr_ai_stopped}S, +{nbr_ai_added}, '
                       f'-{nbr_ai_removed}) | Player ({nbr_player_moving}M, {nbr_player_stopped}S) | '
                       f'Watched ({len(watched_trains)})')
                await send_ch_msg(CH_LOG, msg)
                await asyncio.sleep(.3)
                nbr_ai_added = 0
                nbr_ai_removed = 0

    @tasks.loop(seconds=SCAN_TIME * 1.5)
    async def scan_detectors():
        global detector_files
        global detector_file_time
        global last_world_datetime  # For reporting using server time
        updated_files = list()
        updated_file_time = 0

        detector_files = glob.glob(os.path.join(AEI_PATH, "*.xml"))  # List is alphabetical
        for file in detector_files:
            this_file_time = os.path.getmtime(file)
            if this_file_time > detector_file_time:
                updated_files.append(file)
                updated_file_time = max(updated_file_time, this_file_time)
        for file in updated_files:
            # Grab timestamp of file save (only way to get any kind of timing)
            player_found = False
            tree = ET.parse(file)
            root = tree.getroot()
            report = parseAEI(last_world_datetime, root)
            detector_reports[report.name].append(report)
            defects = list()
            if find_tid_by_symbol(report.symbol, curr_trains) > 0:
                engineer = curr_trains[find_tid_by_symbol(report.symbol, curr_trains)].engineer
            else:
                engineer = "None"
            for unit in report.units:
                if unit.defect.lower() != 'all_ok':
                    defects.append([unit.seq, unit.defect])
            if len(defects) > 0:
                defect_msg = ''
                for defect in defects:
                    defect_msg += f'{defect[1]} @ seq {defect[0]} : '
                defect_msg = defect_msg[:-3]
            else:
                defect_msg = 'None'
            msg = (f'{report.timestamp} DET RPT // {report.name} // {report.symbol} [{engineer}] '
                   f'| {report.speed} mph | {report.axles} axles | Defects: {defect_msg}')
            local_players = players.copy()  # Protect against the players dict being changed while iterating below
            for player in local_players.values():
                if player.train_symbol.lower() in report.symbol.lower():
                    player_found = True
                    # Send report to job thread
                    forum_thread = await bot.fetch_channel(player.job_thread)
                    await send_ch_msg(forum_thread, msg, log=False)
                    await asyncio.sleep(.3)
            if player_found or TRACK_AI_DD:
                await send_ch_msg(CH_DETECTOR, msg)
                await asyncio.sleep(.3)
            else:
                log_msg(msg)  # Go ahead and write AI DD messages to log
        if len(updated_files) > 0:
            detector_file_time = updated_file_time

    @tasks.loop(hours=12)
    async def cleanup_detector_messages():
        keyword = cleanup_detector_messages.keyword
        days_old = cleanup_detector_messages.days_old

        # Try to locate the forum channel by name across all guilds
        forum_channel = None
        for guild in bot.guilds:
            for channel in guild.channels:
                if isinstance(channel, discord.ForumChannel) and channel.name == JOB_POST_FORUM:
                    forum_channel = channel
                    break
            if forum_channel:
                break

        if forum_channel is None:
            stat_msg = f'{last_world_datetime} (CLEANUP DETECTOR MESSAGES): Forum named "{JOB_POST_FORUM}" not found'
            await send_ch_msg(CH_LOG, stat_msg)
            await asyncio.sleep(.3)
            return

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_old)
        stat_msg = (f'{last_world_datetime} (CLEANUP DETECTOR MESSAGES): '
                    f'Scanning {JOB_POST_FORUM} keyword="{keyword}", '
                    f'days_old={days_old}, cutoff={cutoff}')
        await send_ch_msg(CH_LOG, stat_msg)
        await asyncio.sleep(.3)

        for thread in forum_channel.threads:
            if thread.archived:
                continue

            try:
                async for msg in thread.history(limit=None):
                    # Only delete if old enough
                    if msg.created_at > cutoff:
                        continue

                    if not msg.content:
                        continue

                    stat_msg = None
                    if keyword.lower() in msg.content.lower():
                        try:
                            await msg.delete()
                            stat_msg = (f'{last_world_datetime} (CLEANUP DETECTOR MESSAGES): Deleted message '
                                        f'{msg.id} in thread "{thread.name}"')
                        except discord.Forbidden:
                            stat_msg = ('{last_world_datetime} (CLEANUP DETECTOR MESSAGES):'
                                        ' Missing permissions to delete message.')
                        except discord.HTTPException:
                            stat_msg = ('{last_world_datetime} (CLEANUP DETECTOR MESSAGES):'
                                        ' Failed to delete due to API error.')
                    if stat_msg is not None:
                        await send_ch_msg(CH_LOG, stat_msg)
                        await asyncio.sleep(.3)

            except Exception as e:
                stat_msg = (f'{last_world_datetime} (CLEANUP DETECTOR MESSAGES):'
                            f' Error reading thread "{thread.name}": {e}')
                await send_ch_msg(CH_LOG, stat_msg)
                await asyncio.sleep(.3)

    cleanup_detector_messages.keyword = "DET RPT"
    cleanup_detector_messages.days_old = 12

    @bot.event
    async def on_ready():
        global event_db
        global last_world_datetime

        last_world_datetime = None  # Set to None to indicate first time through
        await bot.sync_commands()

        print(f"{datetime.now()} {bot.user} starting r8te v{VERSION}")
        scan_world_state.start()
        scan_detectors.start()
        cleanup_detector_messages.start()

    bot.run(BOT_TOKEN)
