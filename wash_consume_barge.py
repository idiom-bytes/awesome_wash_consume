## 1. Basic Setup including `ocean` and `alice_wallet`
'''
This script was created for me to add my own notes to the Data Farming README.

I believe df.md still offers the best DX to onboard.
https://github.com/oceanprotocol/ocean.py/blob/main/READMEs/df.md

This file should be used along with the blog post to gain additional context.

Our goal in this section is to make sure that:
A) The Ocean library is working.
B) We can get Alice's wallet.
C) We can mint her some OCEAN.
D) We verify she has some OCEAN. 
'''
# A) Create Ocean instance
from ocean_lib.web3_internal.utils import connect_to_network
connect_to_network("development")

from ocean_lib.example_config import ExampleConfig
from ocean_lib.ocean.ocean import Ocean
config = ExampleConfig.get_config("development")
ocean = Ocean(config)

# B) Create Alice's wallet
import os
from brownie.network import accounts
accounts.clear()
alice_private_key = os.getenv("TEST_PRIVATE_KEY1")
alice_wallet = accounts.add(alice_private_key)
print(f"alice_wallet address is {alice_wallet.address}")

## C) Debug give alice some fake OCEAN
import os
os.environ['FACTORY_DEPLOYER_PRIVATE_KEY'] = '0xc594c6e5def4bab63ac29eed19a134c130388f74f019bc74b8f4389df2837a58'
from ocean_lib.ocean.mint_fake_ocean import mint_fake_OCEAN
mint_fake_OCEAN(config) #Alice gets some

# D) Let's verify alice has OCEAN
OCEAN = ocean.OCEAN_token
assert OCEAN.balanceOf(alice_wallet.address) > 0, "Alice has no OCEAN"


## 2. Lock OCEAN for veOCEAN
'''
The best way to understand veOCEAN may be with the announcement blog.
https://blog.oceanprotocol.com/introducing-veocean-c5f416c1f9a0

OCEAN is the coin that drives the economy of Ocean Protocol.
veOCEAN is used to determine how rewards are distributed across the protocol.

We're going to need both tokens to farm data.
We're going to manipulate time so we can play with veOCEAN.
We're going to create a lock.
'''
# A) Simulate passage of time, until next Thursday, the start of DF(X)
from brownie.network import chain
WEEK = 7 * 86400 # seconds in a week
t0 = chain.time()
t1 = t0 // WEEK * WEEK + WEEK #this is a Thursday, because Jan 1 1970 was
t2 = t1 + ((WEEK * 52) * 4) 
chain.sleep(t1 - t0) 
chain.mine()

# B) We're now at the beginning of the epoch / data farming round. So, let's create a lock
# To do that, we're going to need a reference to the veOCEAN contract
veOCEAN = ocean.ve_ocean
# we then set how much OCEAN we want to lock
amt_OCEAN_lock = 10.0

# helper functions
def to_wei(amt_eth) -> int:
    return int(amt_eth * 1e18)
def from_wei(amt_wei: int) -> float:
    return float(amt_wei / 1e18)

# C) we finally approve the OCEAN to be spent and create the lock
OCEAN.approve(veOCEAN.address, to_wei(amt_OCEAN_lock), {"from" : alice_wallet})
veOCEAN.withdraw({"from": alice_wallet}) #withdraw old tokens first
veOCEAN.create_lock(to_wei(amt_OCEAN_lock), t2, {"from": alice_wallet})

assert veOCEAN.balanceOf(alice_wallet.address) > 0, "Alice has no veOCEAN"


## 3. Publish Dataset & FRE
'''
We are now going to configure some parameters to publish our dataset.
We'll obtain all the objects/references needed to allocate veOCEAN, and to consume our own data.
'''

# A) Data Info
name = "Branin dataset"
url = "https://raw.githubusercontent.com/trentmc/branin/main/branin.arff"
# WRT Data Farming, your asset Data Consume Volume (DCV) = datatoken_price_OCEAN * num_consumes.
# Your asset gets rewards pro-rata for its DCV compared to other assets' DCVs. 
datatoken_price_OCEAN = 100.0
num_consumes = 3

# B) Create data asset
(data_NFT, datatoken, asset) = ocean.assets.create_url_asset(name, url, alice_wallet, wait_for_aqua=False)
print(f"Just published asset, with data_NFT.address={data_NFT.address}")

# C) Create fixed-rate exchange (FRE)
from web3 import Web3
exchange_id = ocean.create_fixed_rate(
    datatoken=datatoken,
    base_token=OCEAN,
    amount=to_wei(num_consumes),
    fixed_rate=to_wei(datatoken_price_OCEAN),
    from_wallet=alice_wallet,
)


## 4. Stake on dataset  
# A) Total allocation must be <= 10000 (100.00% stored as uint32)
# We are going to allocate 100% of our veOCEAN to our asset
amt_allocate = 10000
ocean.ve_allocate.setAllocation(amt_allocate, data_NFT.address, chain.id, {"from": alice_wallet})

## 5. Fake-consuming data
'''
"Wash consuming" is when a publisher fake-consumes data.  
This drives data consume volume (DCV). They get more rewards.  
This is not healthy for the ecosystem long-term.  

Good news: if consume fee > weekly rewards, then wash consume becomes unprofitable.  
DF is set up to make this happen by DF29 (if not sooner).
https://twitter.com/trentmc0/status/1587527525529358336)

In the meantime, this README helps level the playing field.  
This step shows how to do fake-consume by consuming data from yourself.  
In the real wordl, fees are still incurred.  
'''

# A) Alice buys datatokens from herself
amt_pay = datatoken_price_OCEAN * num_consumes
OCEAN_bal = from_wei(OCEAN.balanceOf(alice_wallet.address))
assert OCEAN_bal >= amt_pay, f"Have just {OCEAN_bal} OCEAN"
OCEAN.approve(ocean.fixed_rate_exchange.address, to_wei(OCEAN_bal), {"from": alice_wallet})
fees_info = ocean.fixed_rate_exchange.get_fees_info(exchange_id)
for i in range(num_consumes):
    print(f"Purchase #{i+1}/{num_consumes}...")
    tx = ocean.fixed_rate_exchange.buyDT(
        exchange_id,
        to_wei(num_consumes), # datatokenAmount
        to_wei(OCEAN_bal),    # maxBaseTokenAmount
        fees_info[1], # consumeMarketAddress
        fees_info[0], # consumeMarketSwapFeeAmount
        {"from": alice_wallet},
    )
    assert tx, "buying datatokens failed"
DT_bal = from_wei(datatoken.balanceOf(alice_wallet.address))
assert DT_bal >= num_consumes, f"Have just {DT_bal} datatokens"

# B) Alice sends datatokens to the service, to get access. This is the "consume".
for i in range(num_consumes):
    print(f"Consume #{i+1}/{num_consumes}...")
    ocean.assets.pay_for_access_service(asset, alice_wallet)
    #don't need to call e.g. ocean.assets.download_asset() since wash-consuming

## 6. Collect OCEAN rewards
# A) Simulate passage of time, until next Thursday, which is the start of DF(X+1)
WEEK = 7 * 86400 # seconds in a week
MAXTIME = 4 * 365 * 86400
t0 = chain.time()
t1 = t0 # WEEK * WEEK + WEEK
t2 = t1 + WEEK
chain.sleep(t1 - t0) 
chain.mine()

# B) Rewards can be claimed via code or webapp, at your leisure. Let's do it now.
bal_before = from_wei(OCEAN.balanceOf(alice_wallet.address))
ocean.ve_fee_distributor.claim({"from": alice_wallet})
bal_after = from_wei(OCEAN.balanceOf(alice_wallet.address))
print(f"Just claimed {bal_after-bal_before} OCEAN rewards") 

## 7. Repeat steps 1-6, for Eth mainnet
'''
We leave this as an exercise to the reader:)
Here's a hint to get started: initial setup is like:
https://github.com/oceanprotocol/ocean.py/blob/main/READMEs/simple-remote.md

Happy Data Farming!
'''