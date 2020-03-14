'''
This file contains all the code for a single run of Covid-ABM.

Based heavily on LEMOD-FP (https://github.com/amath-idm/lemod_fp).
'''

#%% Imports
import numpy as np # Needed for a few things not provided by pl
import pylab as pl
import sciris as sc
from covid_abm import utils as cov_ut
from . import parameters as cov_pars


# Specify all externally visible functions this file defines
__all__ = ['ParsObj', 'Person', 'Sim', 'single_run', 'multi_run']



#%% Define classes
class ParsObj(sc.prettyobj):
    '''
    A class based around performing operations on a self.pars dict.
    '''

    def __init__(self, pars):
        self.update_pars(pars)
        self.results_keys = ['n_susceptible',
                             'n_exposed',
                             'n_infectious',
                             'n_recovered',
                             'infections',
                             'tests',
                             'diagnoses',
                             'recoveries',
                             'deaths',
                             'cum_exposed',
                             'cum_tested',
                             'cum_diagnosed',
                             'cum_deaths',]
        return

    def __getitem__(self, key):
        ''' Allow sim['par_name'] instead of sim.pars['par_name'] '''
        return self.pars[key]

    def __setitem__(self, key, value):
        ''' Ditto '''
        if key in self.pars:
            self.pars[key] = value
        else:
            suggestion = sc.suggest(key, self.pars.keys())
            if suggestion:
                errormsg = f'Key {key} not found; did you mean "{suggestion}"?'
            else:
                all_keys = '\n'.join(list(self.pars.keys()))
                errormsg = f'Key {key} not found; available keys:\n{all_keys}'
            raise KeyError(errormsg)
        return

    def update_pars(self, pars):
        ''' Update internal dict with new pars '''
        if not isinstance(pars, dict):
            raise TypeError(f'The pars object must be a dict; you supplied a {type(pars)}')
        if not hasattr(self, 'pars'):
            self.pars = pars
        elif pars is not None:
            self.pars.update(pars)
        return


class Person(ParsObj):
    '''
    Class for a single person.
    '''
    def __init__(self, pars, age=0, sex=0):
        super().__init__(pars) # Set parameters
        self.uid  = str(sc.uuid()) # Unique identifier for this person
        self.age  = float(age) # Age of the person (in years)
        self.sex  = sex # Female (0) or male (1)

        # Define state
        self.alive       = True
        self.susceptible = True
        self.exposed     = False
        self.infectious  = False
        self.diagnosed   = False
        self.recovered   = False
        self.dead        = False

        # Keep track of dates
        self.date_exposed    = None
        self.date_infectious = None
        self.date_diagnosed  = None
        self.date_recovered  = None
        self.date_died       = None
        return


class Sim(ParsObj):
    '''
    The Sim class handles the running of the simulation: the number of children,
    number of time points, and the parameters of the simulation.
    '''

    def __init__(self, pars=None, datafile=None):
        if pars is None:
            pars = cov_pars.make_pars()
        super().__init__(pars) # Initialize and set the parameters as attributes
        self.data = None # cov_pars.load_data(datafile)
        self.set_seed(self['seed'])
        self.init_results()
        self.init_people()
        self.interventions = {}
        return

    def set_seed(self, seed=None, reset=False):
        ''' Set the seed for the random number stream '''
        if reset:
            seed = self['seed']
        cov_ut.set_seed(seed)
        return

    @property
    def n(self):
        ''' Count the number of people '''
        return len(self.people)

    @property
    def npts(self):
        ''' Count the number of time points '''
        return int(self['n_days'] + 1)

    @property
    def tvec(self):
        ''' Create a time vector '''
        return np.arange(self['n_days'] + 1)


    def init_results(self):
        ''' Initialize results '''
        self.results = {}
        for key in self.results_keys:
            self.results[key] = np.zeros(int(self.npts))
        self.results['t'] = np.arange(int(self.npts))
        self.results['transtree'] = {} # For storing the transmission tree
        self.results['ready'] = False
        return

    def get_person(self, ind):
        ''' Return a person based on their ID '''
        return self.people[self.uids[ind]]


    def init_people(self, verbose=None):
        ''' Create the people '''
        if verbose is None:
            verbose = self['verbose']

        if verbose>=2:
            print('Creating {self["n"]} people...')

        self.people = {} # Dictionary for storing the people -- use plain dict since faster
        for p in range(int(self['n'])): # Loop over each person
            age,sex = cov_pars.get_age_sex(use_data=self['usepopdata'])
            person = Person(self.pars, age=age, sex=sex) # Create the person
            self.people[person.uid] = person # Save them to the dictionary

        # Store all the UIDs as a list
        self.uids = list(self.people.keys())

        # Create the seed infections
        for i in range(int(self['n_infected'])):
            self.results['infections'][0] += 1
            person = self.get_person(i)
            person.susceptible = False
            person.exposed = True
            person.infectious = True
            person.date_exposed = 0
            person.date_infectious = 0

        return


    def summary_stats(self):
        ''' Compute the summary statistics to display at the end of a run '''
        keys = ['n_susceptible', 'cum_exposed', 'n_infectious', 'cum_deaths']
        summary = {}
        for key in keys:
            summary[key] = self.results[key][-1]
        return summary


    def infect_person(self, source_person, target_person, t, infectious=False):
        '''
        Infect target_person. source_person is used only for constructing the
        transmission tree.
        '''
        target_person.susceptible = False
        target_person.exposed = True
        target_person.date_exposed = t
        incub_dist = cov_ut.sample(target_person.pars['incub'])

        target_person.date_infectious = t + incub_dist

        # Program them to either die or recover
        if cov_ut.bt(target_person.pars['cfr']):
            death_dist = round(pl.normal(target_person.pars['timetodie'], target_person.pars['timetodie_std']))
            target_person.date_died = t + death_dist
        else:
            dur_dist = cov_ut.sample(target_person.pars['dur'])
            target_person.date_recovered = target_person.date_infectious + dur_dist

        self.results['transtree'][target_person.uid] = {'from':source_person.uid, 'date':t}

        return target_person


    def run(self, verbose=None, calc_likelihood=False, do_plot=False, **kwargs):
        ''' Run the simulation '''

        T = sc.tic()

        # Reset settings and results
        if verbose is None:
            verbose = self['verbose']
        self.init_results()
        self.init_people() # Actually create the people
        daily_tests = [] # Number of tests each day, from the data # TODO: fix

        # Main simulation loop
        for t in range(self.npts):

            # Print progress
            if verbose>=1:
                string = f'  Running day {t:0.0f} of {self.pars["n_days"]}...'
                if verbose>=2:
                    sc.heading(string)
                else:
                    print(string)

            test_probs = {} # Store the probability of each person getting tested

            # Update each person
            for person in self.people.values():

                # Count susceptibles
                if person.susceptible:
                    self.results['n_susceptible'][t] += 1
                    continue # Don't bother with the rest of the loop

                # Handle testing probability
                if person.infectious:
                    test_probs[person.uid] = self['symptomatic'] # They're infectious: high probability of testing
                else:
                    test_probs[person.uid] = 1.0

                # If exposed, check if the person becomes infectious
                if person.exposed:
                    self.results['n_exposed'][t] += 1
                    if not person.infectious and t >= person.date_infectious: # It's the day they become infectious
                        person.infectious = True
                        if verbose>=2:
                            print(f'      Person {person.uid} became infectious!')

                # If infectious, check if anyone gets infected
                if person.infectious:

                    # Check for death
                    if person.date_died and t >= person.date_died:
                        person.exposed = False
                        person.infectious = False
                        person.recovered = False
                        person.died = True
                        self.results['deaths'][t] += 1

                    # First, check for recovery
                    if person.date_recovered and t >= person.date_recovered: # It's the day they become infectious
                        person.exposed = False
                        person.infectious = False
                        person.recovered = True
                        self.results['recoveries'][t] += 1
                    else:
                        self.results['n_infectious'][t] += 1 # Count this person as infectious
                        n_contacts = cov_ut.pt(person['contacts']) # Draw the number of Poisson contacts for this person
                        contact_inds = cov_ut.choose_people(max_ind=len(self.people), n=n_contacts) # Choose people at random
                        for contact_ind in contact_inds:
                            exposure = cov_ut.bt(self['r0']/self['dur']/self['contacts']) # Check for exposure per person
                            if exposure:
                                target_person = self.get_person(contact_ind)
                                if target_person.susceptible: # Skip people who are not susceptible
                                    self.results['infections'][t] += 1
                                    self.infect_person(source_person=person, target_person=target_person, t=t)
                                    if verbose>=2:
                                        print(f'        Person {person.uid} infected person {target_person.uid}!')

                # Count people who recovered
                if person.recovered:
                    self.results['n_recovered'][t] += 1

            # Implement testing -- this is outside of the loop over people, but inside the loop over time
            if t<len(daily_tests): # Don't know how long the data is, ensure we don't go past the end
                n_tests = daily_tests.iloc[t] # Number of tests for this day
                if n_tests and not pl.isnan(n_tests): # There are tests this day
                    self.results['tests'][t] = n_tests # Store the number of tests
                    test_probs = pl.array(list(test_probs.values()))
                    test_probs /= test_probs.sum()
                    test_inds = cov_ut.choose_people_weighted(probs=test_probs, n=n_tests)
                    for test_ind in test_inds:
                        tested_person = self.people[test_ind]
                        if tested_person.infectious and cov_ut.bt(self['sensitivity']): # Person was tested and is true-positive
                            self.results['diagnoses'][t] += 1
                            tested_person.diagnosed = True
                            if verbose>=2:
                                        print(f'          Person {person.uid} was diagnosed!')

            # Implement quarantine
            if t == self['intervene']: # TODO: allow multiple interventions
                if verbose>=1:
                    print(f'Implementing intervention on day {t}...')
                self['contacts'] *= (1-self['intervention_eff'])

            if t == self['unintervene']:
                if verbose>=1:
                    print(f'Removing intervention on day {t}...')
                self['contacts'] /= (1-self['intervention_eff'])


        # Compute cumulative results
        self.results['cum_exposed']   = pl.cumsum(self.results['infections'])
        self.results['cum_tested']    = pl.cumsum(self.results['tests'])
        self.results['cum_diagnosed'] = pl.cumsum(self.results['diagnoses'])
        self.results['cum_deaths']    = pl.cumsum(self.results['deaths'])

        # Scale the results
        for reskey in self.results_keys:
            self.results[reskey] *= self['scale']

        # Compute likelihood
        # if calc_likelihood:
        #     self.likelihood()

        # Tidy up
        self.results['ready'] = True
        elapsed = sc.toc(T, output=True)
        if verbose>=1:
            print(f'\nRun finished after {elapsed:0.1f} s.\n')
            summary = self.summary_stats()
            print(f"""Summary:
     {summary['n_susceptible']:5.0f} susceptible
     {summary['n_infectious']:5.0f} infectious
     {summary['cum_exposed']:5.0f} exposed
     {summary['cum_deaths']:5.0f} deaths
               """)

        if do_plot:
            self.plot(**kwargs)

        # Convert to an odict to allow e.g. sim.people[25] later
        self.people = sc.odict(self.people)

        return self.results


    # def likelihood(self, verbose=None):
    #     '''
    #     Compute the log-likelihood of the current simulation based on the number
    #     of new diagnoses.
    #     '''
    #     if verbose is None:
    #         verbose = self['verbose']

    #     if not self.results['ready']:
    #         self.run(calc_likelihood=False, verbose=verbose) # To avoid an infinite loop

    #     loglike = 0
    #     for d,datum in enumerate(self.data['new_positives']):
    #         if not pl.isnan(datum): # Skip days when no tests were performed
    #             estimate = self.results['diagnoses'][d]
    #             p = cov_ps.poisson_test(datum, estimate)
    #             logp = pl.log(p)
    #             loglike += logp
    #             if verbose>=2:
    #                 print(f'  {self.data["date"][d]}, data={datum:3.0f}, model={estimate:3.0f}, log(p)={logp:10.4f}, loglike={loglike:10.4f}')

    #     self.results['likelihood'] = loglike

    #     if verbose>=1:
    #         print(f'Likelihood: {loglike}')

    #     return loglike



    def plot(self, do_save=None, fig_args=None, plot_args=None, scatter_args=None, axis_args=None, as_days=True, font_size=18, use_grid=True, verbose=None):
        '''
        Plot the results -- can supply arguments for both the figure and the plots.

        Parameters
        ----------
        do_save : bool or str
            Whether or not to save the figure. If a string, save to that filename.

        fig_args : dict
            Dictionary of kwargs to be passed to pl.figure()

        plot_args : dict
            Dictionary of kwargs to be passed to pl.plot()

        as_days : bool
            Whether to plot the x-axis as days or time points

        Returns
        -------
        Figure handle
        '''

        if verbose is None:
            verbose = self['verbose']
        if verbose:
            print('Plotting...')

        if fig_args     is None: fig_args     = {'figsize':(26,16)}
        if plot_args    is None: plot_args    = {'lw':3, 'alpha':0.7}
        if scatter_args is None: scatter_args = {'s':150, 'marker':'s'}
        if axis_args    is None: axis_args    = {'left':0.1, 'bottom':0.05, 'right':0.9, 'top':0.97, 'wspace':0.2, 'hspace':0.25}

        fig = pl.figure(**fig_args)
        pl.subplots_adjust(**axis_args)
        pl.rcParams['font.size'] = font_size

        res = self.results # Shorten since heavily used

        # Plot everything
        colors = sc.gridcolors(5)
        to_plot = sc.odict({ # TODO
            'Total counts': sc.odict({'n_susceptible':'Number susceptible',
                                      'n_exposed':'Number exposed',
                                      'n_infectious':'Number infectious',
                                      'cum_diagnosed':'Number diagnosed',
                                      'cum_deaths':'Number of deaths',
                                    }),
            'Daily counts': sc.odict({'infections':'New infections',
                                      'tests':'Number of tests',
                                      'diagnoses':'New diagnoses',
                                      'deaths':'New deaths',
                                     }),
            })

        # data_mapping = {
        #     'cum_diagnosed': pl.cumsum(self.data['new_positives']),
        #     'tests':         self.data['new_tests'],
        #     'diagnoses':     self.data['new_positives'],
        #     }

        for p,title,keylabels in to_plot.enumitems():
            pl.subplot(2,1,p+1)
            for i,key,label in keylabels.enumitems():
                this_color = colors[i+p]
                y = res[key]
                pl.plot(res['t'], y, label=label, **plot_args, c=this_color)
                # if key in data_mapping:
                #     pl.scatter(self.data['day'], data_mapping[key], c=[this_color], **scatter_args)
            # pl.scatter(pl.nan, pl.nan, c=[(0,0,0)], label='Data', **scatter_args)
            pl.grid(use_grid)
            cov_ut.fixaxis(self)
            # pl.ylabel('Count')
            pl.xlabel('Days')
            pl.title(title)

        # Ensure the figure actually renders or saves
        if do_save:
            if isinstance(do_save, str):
                filename = do_save # It's a string, assume it's a filename
            else:
                filename = 'covid_abm_results.png' # Just give it a default name
            pl.savefig(filename)

        pl.show()

        return fig


    def plot_people(self):
        ''' Use imshow() to show all individuals as rows, with time as columns, one pixel per timestep per person '''
        raise NotImplementedError


def single_run(sim=None, noise=0.0, ind=0, verbose=None, **kwargs):
    '''
    Convenience function to perform a single simulation run. Mostly used for
    parallelization, but can also be used directly:
        import covid_abm
        sim = covid_abm.single_run() # Create and run a default simulation
    '''
    if sim is None:
        new_sim = Sim(**kwargs)
    else:
        new_sim = sc.dcp(sim) # To avoid overwriting it; otherwise, use

    new_sim['seed'] += ind # Reset the seed, otherwise no point of parallel runs
    new_sim.set_seed(new_sim['seed'])
    new_sim['r0'] *= 1+noise*pl.randn() # Optionally add noise
    new_sim.run(verbose=verbose)

    return new_sim


def multi_run(sim=None, n=4, noise=0.0, verbose=None, **kwargs):
    '''
    For running multiple runs in parallel. Example:
        import covid_seattle
        sim = covid_seattle.Sim()
        sims = covid_seattle.multi_run(sim, n=6, noise=0.2)
    '''
    if sim is None:
        sim = Sim(**kwargs)

    # Copy the simulations
    iterkwargs = {'ind':np.arange(n)}
    kwargs = {'sim':sim, 'noise':noise, 'verbose':verbose}
    sims = sc.parallelize(single_run, iterkwargs=iterkwargs, kwargs=kwargs)

    return sims


