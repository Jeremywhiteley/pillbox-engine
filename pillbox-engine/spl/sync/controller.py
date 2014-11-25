from __future__ import print_function

import os
import sys
import time
import fnmatch

from django.conf import settings

from spl.models import SetInfo, ProductData, Source, Ingredient, Task
from spl.sync.xpath import XPath


class Controller(object):
    """ This class is specificaly written to work with celery task management """

    def __init__(self, celery=None, stdout=None):
        self.stdout = stdout
        self.celery = celery

    def sync(self, action):
        """ Class's main method/hook for activating sync sequence

        @params
        - action: choices are pills | products | all
        """
        arguments = ['products', 'pills', 'all']

        if action in arguments:
            self._update(action)

    def _update(self, action):
        start = time.time()

        x = XPath()

        sources = Source.objects.all().values('title')

        folders = [s['title'] for s in sources]

        counter = {
            'added': 0,
            'updated': 0
        }

        for folder in folders:
            d = '%s/%s' % (settings.SPL_RAW_DATA, folder)
            files = os.listdir(d)

            for f in files:
                if fnmatch.fnmatch(f, '*.xml'):
                    output = getattr(x, action)(f, d)
                    if output:
                        counter = getattr(self, '_%s' % action)(output, counter)

                    self._status(added=counter['added'], updated=counter['updated'],
                                 error=x.error, skipped=x.skip,
                                 action=action)

        end = time.time()

        self._time_spent(start, end)

    def _all(self, data, counter):
        """ Triggers and manages products and pill methods """

        counter = self._products(data['products'], counter)
        counter = self._pills(data['pills'], counter)

        return counter

    def _products(self, data, counter):

        setid = data['setid']
        data.pop('setid')

        updated_values = data

        obj, created = SetInfo.objects.update_or_create(setid=setid, defaults=updated_values)

        if created:
            counter['added'] += 1
        elif obj:
            counter['updated'] += 1

        return counter

    def _pills(self, data_set, counter):

        for data in data_set:
            id = data['id']
            data.pop('id')

            ingredients = data['ingredients']
            data.pop('ingredients')

            # Update ingredients
            for item in ingredients:
                ingredient_id = item['id']
                updated_values = {
                    'code_system': item['code_system'],
                    'name': item['name'],
                    'class_code': item['class_code']
                }

                obj, created = Ingredient.objects.get_or_create(id=ingredient_id, defaults=updated_values)

            # Update pills
            updated_values = data

            obj, created = ProductData.objects.update_or_create(id=id, defaults=updated_values)

            if created:
                counter['added'] += 1
            elif obj:
                counter['updated'] += 1

        return counter

    def _time_spent(self, start, end):

        spent = end - start
        minutes = spent / 60
        seconds = spent % 60

        if self.celery:
            task = Task.objects.get(task_id=self.celery.task_id)
            task.time_ended = end
            task.duration = spent
            task.save()

        if self.stdout:
            self.stdout.write('\nTime spent : %s minues and %s seconds' % (int(minutes), round(seconds, 2)))

    def _status(self, **kwarg):

        if self.stdout:
            self.stdout.write('added:%s | updated:%s | error:%s | skipped: %s' %
                              (kwarg['added'], kwarg['updated'], kwarg['error'], kwarg['skipped']), ending='\r')
            sys.stdout.flush()

        if self.celery:
            self.celery.update_state(state='PROGRESS',
                                     meta={'added': kwarg['added'],
                                           'updated': kwarg['updated'],
                                           'error': kwarg['error'],
                                           'skipped': kwarg['skipped'],
                                           'action': kwarg['action']})