This is an example set of posts to use for giving a brief list of instructions on interacting with r8te
(Broken up due to Discord character limits)

Post 1------------------------------------

# Interacting with the Job Tracking System:
The job tracking system here utilizes a Discord bot to streamline operations.
As opposed to some other Run8 servers you may have encountered, there is no need for you to interact directly with a job
post tag, instead you will issue a few commands to let the bot know your intentions.
At present, usage of the bot is optional but encouraged. A side benefit of dealing with jobs in this way is that the bot
will be able to track your train movements in order to provide neat trackers, such as defect reports to help remember
which car still has handbrakes tied and now flat wheels, or log your hours worked.


## Command: **/crew**
When taking a job (as either a new job, or a re-crew), you will use the command `/crew <locomotive symbol>`
So, for example, if you were going to work the BARBAK job, and the lead loco is tagged as "M-BARBAK-29", you would issue
the command from within the BARBAK job posting:
`/crew M-BARBAK-29`

The bot should acknowledge your request, and present you with a message stating that you have crewed that job.
If the bot responds that the train is not found, double-check the tag in-game to make sure your command matches that tag
(upper or lower case does not matter).

Upon successfully crewing the job, the bot will change the job post tag from `Available` to `In Progress`

When `/crew`ing a job, if your train is stationary whether you are afk or being held up by Otto, the bot will begin to
pester you, providing a reminder in case you forgot to ``/tie_down`. Please note that the bot will only pester you when
working non-yard related jobs.

In some off-chance that the bot is unable to find the train in the world, wait up to 2 minutes before trying the
`/crew` again.

Post 2------------------------------------

## Command: **/tie_down**
If you need to leave a job before it is complete, you will use the `/tie_down` command. This command requires you to
enter a description of where you are tied down. For example:
`/tie_down Jim Grey siding.`

Feel free to also leave some info for the next crew within the `/tie_down` message. For example:
`/tie_down Modesto T3. Setouts for Riverside still need to be done`

Upon successfully tying down, the bot will change the job post tag from `In Progress` to `Available`


## Command: **/complete**
The final command is used to mark a job as complete, and simply uses the `/complete` command with an optional note:

`/complete BAR R3 - power still attached`

This will change the job post tag from "In Progress" to "Complete"

Post 3------------------------------------

## Command :**/mark_available**
For certain jobs, players will be assembling trains for future work. When that train has been assembled, the job post
will need to be marked as available, and some information on that train needs to be supplied. 
Using the`/mark_available` command comes into play here. 
This command has two required parameters, as well as two optional ones:
`mark_available <loco lumber> <train location> <loco symbol (optional)> <train info (optional)>`.
For example, if you recently worked in Barstow yard and assembled the Boron loco on local track 2, 
with SF leader number 185, a minimal command would be:
(*note: the < and > symbols shown below are to delineate the separate parameters, they do not need to be typed*):

`/mark_available <185> <local T2>`

However, you are encouraged to give the players more info, for example:
`/mark_available <SF-185> <Local T2> <Boron> <13Lds | 18mtys | 4812T | 3018ft | 2x0 | 2.4HpT>`

Executing this command will mark that job as `Available` and create an entry in the job post detailing the train info
you supply.


## Command :**/staff_help**

If you find yourself in a situation while working a job which requires staff intervention, utilize this command to
notify staff and optionally add a note with any details. For example:
`/staff_help <I can't get this train started on the grade>`

