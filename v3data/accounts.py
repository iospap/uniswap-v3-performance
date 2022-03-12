from v3data import GammaClient
from v3data.gamma import GammaPrice
from v3data.constants import XGAMMA_ADDRESS


class AccountData:
    def __init__(self, chain: str, account_address: str):
        self.gamma_client = GammaClient(chain)
        self.address = account_address.lower()
        self.reward_hypervisor_address = XGAMMA_ADDRESS
        self.decimal_factor = 10**18

    async def _get_data(self):
        query = """
        query accountData($accountAddress: String!, $rewardHypervisorAddress: String!) {
            account(
                id: $accountAddress
            ){
                parent { id }
                gammaDeposited
                gammaEarnedRealized
                hypervisorShares {
                    hypervisor {
                        id
                        pool{
                            token0{ decimals }
                            token1{ decimals }
                        }
                        conversion {
                            baseTokenIndex
                            priceTokenInBase
                            priceBaseInUSD
                        }
                        totalSupply
                        tvl0
                        tvl1
                        tvlUSD
                    }
                    shares
                    initialToken0
                    initialToken1
                    initialUSD
                }
                rewardHypervisorShares{
                    rewardHypervisor { id }
                    shares
                }
            }
            rewardHypervisor(
                id: $rewardHypervisorAddress
            ){
                totalGamma
                totalSupply
            }
        }
        """
        variables = {
            "accountAddress": self.address,
            "rewardHypervisorAddress": self.reward_hypervisor_address,
        }

        response = await self.gamma_client.query(query, variables)
        self.data = response["data"]


class AccountInfo(AccountData):
    def _returns(self):
        returns = {}
        for share in self.data["account"]["hypervisorShares"]:
            if int(share["shares"]) <= 0:  # Workaround before fix in subgraph
                continue
            hypervisor_address = share["hypervisor"]["id"]
            initial_token0 = int(share["initialToken0"])
            initial_token1 = int(share["initialToken1"])
            initial_USD = float(share["initialUSD"])
            shareOfPool = int(share["shares"]) / int(share["hypervisor"]["totalSupply"])
            tvl_USD = float(share["hypervisor"]["tvlUSD"])

            conversion = share["hypervisor"]["conversion"]

            base_token_index = int(conversion["baseTokenIndex"])
            price_token_in_base = float(conversion["priceTokenInBase"])
            price_base_in_usd = float(conversion["priceBaseInUSD"])

            if base_token_index == 0:
                token = initial_token1
                base = initial_token0
            elif base_token_index == 1:
                token = initial_token0
                base = initial_token1

            initial_token_current_USD = (
                token * price_token_in_base * price_base_in_usd
            ) + (base * price_base_in_usd)
            current_USD = shareOfPool * tvl_USD

            returns[hypervisor_address] = {
                "initialTokenUSD": initial_USD,
                "initialTokenCurrentUSD": initial_token_current_USD,
                "currentUSD": current_USD,
                "netMarketReturns": current_USD - initial_USD,
                "netMarketReturnsPercentage": f"{1 - (initial_USD / current_USD):.2%}",
                "hypervisorReturns": current_USD - initial_token_current_USD,
                "hypervisorReturnsPercentage": f"{1 - (initial_token_current_USD / current_USD):.2%}",
            }

        return returns

    async def output(self, get_data=True):

        if get_data:
            await self._get_data()

        if not self.data["account"]:
            return {}

        reward_hypervisor_shares = self.data["account"]["rewardHypervisorShares"]
        xgamma_shares = 0
        for shares in reward_hypervisor_shares:
            if (
                shares.get("rewardHypervisor", {}).get("id")
                == self.reward_hypervisor_address
            ):
                xgamma_shares = int(shares["shares"])

        totalGammaStaked = int(self.data["rewardHypervisor"]["totalGamma"])
        xgamma_virtual_price = totalGammaStaked / int(
            self.data["rewardHypervisor"]["totalSupply"]
        )

        # Get pricing
        gamma_pricing = await GammaPrice().output()

        account_owner = self.data["account"]["parent"]["id"]
        gammaStaked = (xgamma_shares * xgamma_virtual_price) / self.decimal_factor
        gammaDeposited = (
            int(self.data["account"]["gammaDeposited"]) / self.decimal_factor
        )
        gammaEarnedRealized = (
            int(self.data["account"]["gammaEarnedRealized"]) / self.decimal_factor
        )
        gammaStakedShare = gammaStaked / (totalGammaStaked / self.decimal_factor)
        pendingGammaEarned = gammaStaked - gammaDeposited
        totalGammaEarned = gammaStaked - gammaDeposited + gammaEarnedRealized
        account_info = {
            "owner": account_owner,
            "gammaStaked": gammaStaked,
            "gammaStakedUSD": gammaStaked * gamma_pricing["gamma_in_usdc"],
            "gammaDeposited": gammaDeposited,
            "pendingGammaEarned": pendingGammaEarned,
            "pendingGammaEarnedUSD": pendingGammaEarned
            * gamma_pricing["gamma_in_usdc"],
            "totalGammaEarned": totalGammaEarned,
            "totalGammaEarnedUSD": totalGammaEarned * gamma_pricing["gamma_in_usdc"],
            "gammaStakedShare": f"{gammaStakedShare:.2%}",
            "xgammaAmount": xgamma_shares / self.decimal_factor,
        }
        # The below for compatability
        account_info.update(
            {
                "visrStaked": account_info["gammaStaked"],
                "visrDeposited": account_info["gammaDeposited"],
                "totalVisrEarned": account_info["totalGammaEarned"],
                "visrStakedShare": account_info["gammaStakedShare"],
            }
        )

        returns = self._returns()

        for hypervisor in self.data["account"]["hypervisorShares"]:
            if int(hypervisor["shares"]) <= 0:  # Workaround before fix in subgraph
                continue
            hypervisor_id = hypervisor["hypervisor"]["id"]
            shares = int(hypervisor["shares"])
            totalSupply = int(hypervisor["hypervisor"]["totalSupply"])
            shareOfSupply = shares / totalSupply if totalSupply > 0 else 0
            tvlUSD = float(hypervisor["hypervisor"]["tvlUSD"])
            decimal0 = int(hypervisor["hypervisor"]["pool"]["token0"]["decimals"])
            decimal1 = int(hypervisor["hypervisor"]["pool"]["token1"]["decimals"])
            tvl0_decimal = float(hypervisor["hypervisor"]["tvl0"]) / 10**decimal0
            tvl1_decimal = float(hypervisor["hypervisor"]["tvl1"]) / 10**decimal1

            account_info[hypervisor_id] = {
                "shares": shares,
                "shareOfSupply": shareOfSupply,
                "balance0": tvl0_decimal * shareOfSupply,
                "balance1": tvl1_decimal * shareOfSupply,
                "balanceUSD": tvlUSD * shareOfSupply,
                "returns": returns[hypervisor_id],
            }

        return account_info
