A rough outline on how to operate jobs with r8te:

There are three commands for players to interact with r8te in terms of handling job tracking:

##### /crew < symbol >:

Used to tell the bot that the player is crewing a particular locomotive (designated by its symbol). 
_This symbol must be unique within the server_;. When the player successfully crews a locomotive, they will also be 
marked down as running the particular job that corresponds to the post they executed the /crew command in.

For example, there is a job posting titled:

### H-BAKBAR : Yard transfer from Bakersfield to Barstow
The player executes the bot command: 
`/crew h-bakbar-01`
(this shows that the job title doesn't necessarily have to list the exact symbol of the in-game locomotive)
They have now indicated they are working that job, and crewing the lead locomotive with the tag h-bakbar-01

The bot will change the `Available` tag to `In Progress`

At this point, the bot will track the locomotive tagged "h-bakbar-01", will log AEI/DD events, and notify the player if 
they are stationary too long. A database entry is also generated logging when the player began working this job.

##### /tie_down < location note >:

If a player wants to take a break, they indicate to the bot where they are tying down such as:
`/tid_down Woodford siding`

The bot will change the job tag from `In Progress` to `Available` and will the bot will stop tracking this particular
locomotive symbol. A database entry will be added which indicates the time and tie down location.


##### /complete < symbol >  < notes (opt) >:

Alternatively, when a player finishes a job they will issue a command such as:
`/complete H-BAKBAR-01  All cars on T2, power tied down on T9.`

The bot will change the job tag from `In Progress` to `Completed`, will stop tracking this particular locomotive symbol,
and make a database entry indicating time and date and job complete.

----------
## Yard work


For yard jobs, multiple players can work a job - each must crew a locomotive symbol which is both unique, and labelled 
such that it contains one of the ignored keywords. For example, `switch` `trim` `pwr` `hump` 
(as configured in r8te.cfg).

For example, Barstow may have the following trim sets on the server:

BAR TRIM 201
BAR TRIM 202

Within a yard job post, a player would crew one of these power sets:
`/crew bar trim 201`
The bot will change the job post tag from `Available` to `In Progress`

Now, at any time, another player can also work in the yard by crewing a different locomotive with an "ignored" keyword:
`/crew bar hump`
Since the job is already `In Progress`, no tag change is required. The job will show as two players working it. 

The bot will allow players to `/tie_down` as normal; however, if they try to `/complete` a job and there are more
players still crewing, the person trying to `/complete` the job will instead just tie down their loco.




