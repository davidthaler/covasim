'''
Set the parameters for COVID-ABM.
'''

import pylab as pl
from datetime import datetime


__all__ = ['make_pars', 'get_age_sex']


def make_pars():
    ''' Set parameters for the simulation '''
    pars = {}

    # Simulation parameters
    pars['scale']      = 1 # Factor by which to scale results

    pars['n']          = 10000 // pars['scale'] # Number ultimately susceptible to CoV
    pars['n_infected'] = 1 // pars['scale'] # Asked for 1000 in Seattle's population
    pars['day_0']      = datetime(2020, 1, 15) # Start day of the epidemic
    pars['n_days']     = (datetime(2020, 3, 9)-pars['day_0']).days # How many days to simulate Apr/30
    pars['seed']       = 1 # Random seed, if None, don't reset
    pars['verbose']    = 1 # Whether or not to display information during the run -- options are 0 (silent), 1 (default), 2 (everything)
    pars['usepopdata'] = 0 # Whether or not to load actual population data

    # Epidemic parameters
    pars['r_contact']      = 2.9/(10*20) # Updated to match Mike's distributions
    pars['contacts']       = 20 # Number of contacts per guest per day, estimated
    pars['incub']          = 4.0 # Using Mike's Snohomish number
    pars['incub_std']      = 1.0 # Standard deviation of the serial interval, estimated
    pars['dur']            = 12 # Using Mike's Snohomish number
    pars['dur_std']        = 3 # Variance in duration
    pars['sensitivity']    = 1.0 # Probability of a true positive, estimated
    pars['symptomatic']    = 5 # Increased probability of testing someone symptomatic, estimated
    pars['cfr']            = 0.02 # Case fatality rate
    pars['timetodie']      = 22 # Days until death
    pars['timetodie_std']  = 2 # STD


    # Events
    pars['quarantine']       = -1  # Day on which quarantine took effect
    pars['unquarantine']     = -1  # Day on which unquarantine took effect
    pars['quarantine_eff']   = 1.00 # Change in transmissibility due to quarantine, estimated

    return pars


def get_age_sex(min_age=0, max_age=99, age_mean=40, age_std=15, use_data=True):
    '''
    Define age-sex distributions.
    '''
    if use_data:
        try:
            import synthpops as sp
        except ImportError as E:
            raise ImportError(f'Could not load synthpops; set sim["usepopdata"] = False or install ({str(E)})')
        age, sex = sp.get_seattle_age_sex()
    else:
        sex = pl.randint(2) # Define female (0) or male (1) -- evenly distributed
        age = pl.normal(age_mean, age_std) # Define age distribution for the crew and guests
        age = pl.median([min_age, age, max_age]) # Normalize
    return age, sex


