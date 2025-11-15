Structures

Train: Parsed from the Run8 WorldSave.xml. 
In R8TE, the concept of a train means the first rail vehicle in the XML "TrainLoader" structure is a locomotive. 
During a world save parsing cycle, the code walks through the XML and creates a dictionary keyed off the unique train ID.
We are interested in trains which are crewed either by AI or Players - we don't track trains which are not crewed.
To determine if a train is crewed we look at the XML TrainLoader attribute "TrainWasAI". If that is true we know
that particular train is crewed - but not by a player. The engineer of that train is then named "AI".

**Crewing** a train:
In order for the bot to track where a player controlled train is in the world, we have the concept of *crewing* a train.
To crew a train, the player must specify a train symbol of a locomotive in the world. Player crews are kept track of
via the `player_crews` dictionary. 

Working a **Job**:
When a player successfully _crews_ a train, the bot will also note the player as _working a job_. The job info is 
discovered by the bot based on the job post thread in the discord server. 
**Note** that this is distinct from crewing a train. Jobs are kept track of via the `working_jobs` dictionary.

