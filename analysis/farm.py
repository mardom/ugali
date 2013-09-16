#!/usr/bin/env python

"""
Class to farm out analysis tasks.

Classes
    Mask

Functions
    someFunction
"""

import os
import sys
import numpy
import healpy
import subprocess
import time

import ugali.analysis.isochrone
import ugali.analysis.kernel
import ugali.analysis.likelihood
import ugali.observation.catalog
import ugali.observation.mask
import ugali.utils.parse_config
import ugali.utils.skymap

############################################################

class Farm:
    """
    The Farm class is the master analysis coordinator.
    """

    def __init__(self, config, catalog=None):
        
        self.config = ugali.utils.parse_config.Config(config)
        if catalog is not None:
            self.catalog = catalog
        else:
            self.catalog = ugali.observation.catalog.Catalog(self.config)

    def farmMaskFromCatalog(self, local=True):
        """
        Given an object catalog, farm out the task of creating a mask.
        """
        
        pix, subpix = ugali.utils.skymap.surveyPixel(self.catalog.lon, self.catalog.lat,
                                                     self.config.params['coords']['nside_mask_segmentation'],
                                                     self.config.params['coords']['nside_pixel'])

        print '=== Mask From Catalog ==='

        for infile in [self.config.params['mangle']['infile_1'],
                       self.config.params['mangle']['infile_2']]:

            print 'Mangle infile = %s'%(infile)

            if infile == self.config.params['mangle']['infile_1']:
                savedir = self.config.params['output']['savedir_mag_1_mask']
            elif infile == self.config.params['mangle']['infile_2']:
                savedir = self.config.params['output']['savedir_mag_2_mask']
            else:
                print 'WARNING: did not recognize the Mangle file %s.'%(infile)

            if not os.path.exists(savedir):
                os.mkdir(savedir)
            
            print 'Savedir = %s'%(savedir)
            
            for ii in range(0, len(pix)):

                theta, phi =  healpy.pix2ang(self.config.params['coords']['nside_mask_segmentation'], pix[ii])
                lon, lat = numpy.degrees(phi), 90. - numpy.degrees(theta)
                
                print '  (%i/%i) pixel %i nside %i; %i query points; %s (lon, lat) = (%.3f, %.3f)'%(ii, len(pix), pix[ii],
                                                                                                    self.config.params['coords']['nside_mask_segmentation'],
                                                                                                    len(subpix[ii]),
                                                                                                    self.config.params['coords']['coordsys'],
                                                                                                    lon, lat)

                outfile = '%s/mask_%010i_nside_pix_%i_nside_subpix_%i_%s.fits'%(savedir,
                                                                                pix[ii],
                                                                                self.config.params['coords']['nside_mask_segmentation'],
                                                                                self.config.params['coords']['nside_pixel'],
                                                                                self.config.params['coords']['coordsys'].lower())
                # Check to see if outfile exists
                if os.path.exists(outfile):
                    print '  %s already exists. Skipping ...'%(outfile)
                    continue
                
                if local:
                    self.runFarmMaskFromCatalog(pix[ii], infile, outfile)
                else:
                    # Submit to queue
                    pass                

    def runFarmMaskFromCatalog(self, pix, infile, outfile):
        """
        
        """
        subpix = ugali.utils.skymap.subpixel(pix,
                                             self.config.params['coords']['nside_mask_segmentation'],
                                             self.config.params['coords']['nside_pixel'])
        
        theta, phi =  healpy.pix2ang(self.config.params['coords']['nside_pixel'], subpix)
        lon, lat = numpy.degrees(phi), 90. - numpy.degrees(theta)

        # Conversion between coordinate systems of object catalog and Mangle mask
        if self.config.params['coords']['coordsys'].lower() == 'cel' \
               and self.config.params['mangle']['coordsys'].lower() == 'gal':
            lon, lat = ugali.utils.projector.celToGal(lon, lat)
        elif self.config.params['coords']['coordsys'].lower() == 'gal' \
                 and self.config.params['mangle']['coordsys'].lower() == 'cel':
            lon, lat = ugali.utils.projector.galToCel(lon, lat)
        else:
            pass
            
        maglim = ugali.observation.mask.readMangleFile(infile, lon, lat, index = pix)
        data_dict = {'MAGLIM': maglim}
        ugali.utils.skymap.writeSparseHealpixMap(subpix, data_dict, self.config.params['coords']['nside_pixel'],
                                                 outfile, coordsys=self.config.params['coords']['coordsys'])
        
    def farmLikelihoodFromCatalog(self, local=True, coords=None):
        """
        Given an object catalog, farm out the task of evaluating the likelihood.

        Optional parameter is a set of coordinates (lon, lat) in degrees, which
        returns the corresponding likelihood object for that position on the sky.
        """
        pix = ugali.utils.skymap.surveyPixel(self.catalog.lon, self.catalog.lat,
                                             self.config.params['coords']['nside_likelihood_segmentation'])

        if not os.path.exists(self.config.params['output']['savedir_likelihood']):
            os.mkdir(self.config.params['output']['savedir_likelihood'])

        if coords is not None:
            lon, lat = coords
            theta = numpy.radians(90. - lat)
            phi = numpy.radians(lon)
            pix_coords = healpy.ang2pix(self.config.params['coords']['nside_likelihood_segmentation'], theta, phi)
            if pix_coords not in pix:
                print 'WARNING: coordinates (%.3f, %.3f) not in analysis region'%(lon, lat)
                return -999

        # Save the current configuation settings
        if not local:
            configfile_queue = '%s/config_queue.py'%(self.config.params['output']['savedir_likelihood'])
            self.config.writeConfig(configfile_queue)

        print '=== Likelihood From Catalog ==='
        for ii in range(0, len(pix)):

            # Just for testing
            #if ii >= 2:
            #    continue

            if coords is not None:
                if pix[ii] != pix_coords:
                    continue
            
            theta, phi =  healpy.pix2ang(self.config.params['coords']['nside_likelihood_segmentation'], pix[ii])
            lon, lat = numpy.degrees(phi), 90. - numpy.degrees(theta)

            n_query_points = healpy.nside2npix(self.config.params['coords']['nside_pixel']) \
                             / healpy.nside2npix(self.config.params['coords']['nside_likelihood_segmentation'])

            print '  (%i/%i) pixel %i nside %i; %i query points; %s (lon, lat) = (%.3f, %.3f)'%(ii, len(pix), pix[ii],
                                                                                                self.config.params['coords']['nside_likelihood_segmentation'],
                                                                                                n_query_points,
                                                                                                self.config.params['coords']['coordsys'],
                                                                                                lon, lat)

            # Should actually check to see if outfile exists
            outfile = '%s/likelihood_%010i_nside_pix_%i_nside_subpix_%i_%s.fits'%(self.config.params['output']['savedir_likelihood'],
                                                                                  pix[ii],
                                                                                  self.config.params['coords']['nside_likelihood_segmentation'],
                                                                                  self.config.params['coords']['nside_pixel'],
                                                                                  self.config.params['coords']['coordsys'].lower())
            
            if os.path.exists(outfile) and coords is None:
                print '  %s already exists. Skipping ...'%(outfile)
                continue
                
            if local:
                if coords is None:
                    likelihood = self.runFarmLikelihoodFromCatalog(pix[ii], outfile)
                else:
                    likelihood = self.runFarmLikelihoodFromCatalog(pix[ii], outfile, debug=True)
                    return likelihood
            else:
                # Submit to queue
                if self.config.params['queue']['cluster'] == 'midway':
                    logfile = '%s/%s_%i.log'%(self.config.params['output']['logdir_likelihood'], self.config.params['queue']['jobname'], pix[ii])
                    command = '%s %s %i %s'%(self.config.params['queue']['script'], configfile_queue, pix[ii], outfile)
                    command_queue = 'sbatch --account=kicp --partition=kicp-ht --output=%s --job-name=%s --mem=10000 %s'%(logfile, self.config.params['queue']['jobname'], command)
                    print command_queue
                    
                    if not os.path.exists(self.config.params['output']['logdir_likelihood']):
                        os.mkdir(self.config.params['output']['logdir_likelihood'])

                    while True:
                        n_submitted = int(subprocess.Popen('squeue -u bechtol | wc\n', 
                                                           shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE).communicate()[0].split()[0]) - 1
                        if n_submitted < 100:
                            break
                        else:
                            print '%i jobs already in queue, waiting ...'%(n_submitted)
                            time.sleep(15)

                    os.system(command_queue)
                    #break

    def runFarmLikelihoodFromCatalog(self, pix, outfile, debug=False):
        """
        Set up and run the likelihood analysis
        """
        theta, phi =  healpy.pix2ang(self.config.params['coords']['nside_likelihood_segmentation'], pix)
        lon, lat = numpy.degrees(phi), 90. - numpy.degrees(theta)
        
        roi = ugali.observation.roi.ROI(self.config, lon, lat)

        mask_1 = ugali.observation.mask.MaskBand(self.config.params['mask']['infile_1'], roi)
        mask_2 = ugali.observation.mask.MaskBand(self.config.params['mask']['infile_2'], roi)
        mask = ugali.observation.mask.Mask(self.config, mask_1, mask_2)

        cut = mask.restrictCatalogToObservableSpace(self.catalog)
        catalog = self.catalog.applyCut(cut)
        
        isochrones = []
        for ii, name in enumerate(self.config.params['isochrone']['infiles']):
            isochrones.append(ugali.analysis.isochrone.Isochrone(self.config, name))
        isochrone = ugali.analysis.isochrone.CompositeIsochrone(isochrones, self.config.params['isochrone']['weights'])

        # TODO: Only set up to use Plummer profile at the moment
        kernel = ugali.analysis.kernel.Plummer(lon, lat, self.config.params['kernel']['params'][0])

        likelihood = ugali.analysis.likelihood.Likelihood(self.config, roi, mask, self.catalog, isochrone, kernel)
        
        if not debug:
            likelihood.precomputeGridSearch(self.config.params['likelihood']['distance_modulus_array'])
            likelihood.gridSearch()
            likelihood.write(outfile)
        
        return likelihood
    
############################################################

#def main():
#    """
#    Placeholder for when users want to call this script as an executable
#    """
#    from optparse import OptionParser
    
if __name__ == "__main__":
    #main()
    config = sys.argv[1]
    pix = int(sys.argv[2])
    outfile = sys.argv[3]
    my_farm = Farm(config)
    my_farm.runFarmLikelihoodFromCatalog(pix, outfile)
